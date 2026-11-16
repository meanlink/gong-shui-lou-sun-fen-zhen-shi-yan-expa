"""夜巡大批样本分段接入。

生命周期：collecting（收段中）→ ready（齐备确认通过）→ published（发布为完整 Dataset）；
确认/整批校验失败进入 failed 并保留已收内容；任意未发布阶段可 revoke → revoked。
发布与撤销均为单事务条件状态迁移，并发相撞只有一方成功。
"""
import math
import time
from fastapi import HTTPException
from sqlalchemy import select, update, delete, func
from src.models import Dataset, TransferBatch, TransferSegment
from src.services.business import metadata
from src.services.canonical import canonicalize_rows
from src.utils.serialization import checksum

ISSUE_SAMPLE_LIMIT = 50
# 仅这些状态允许继续收段；撤销/发布完成后的迟到收段一律拒绝
ACCEPT_SEGMENT_STATUSES = ('collecting',)
# 允许撤销的状态：已发布批次不可撤销，已撤销幂等返回
REVOCABLE_STATUSES = ('collecting', 'ready', 'failed')


def open_transfer(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(TransferBatch).where(TransferBatch.name == name)):
        raise HTTPException(409, '该分段批次名已存在，请修改名称')
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '同名数据批次已存在，请修改名称')
    now = time.time()
    batch = TransferBatch(
        name=name, source=data.source, total_segments=data.total_segments,
        total_rows=data.total_rows, batch_checksum=data.batch_checksum.lower(),
        status='collecting', issue={}, created_by=user.id,
        created_at=now, updated_at=now,
    )
    db.add(batch)
    db.flush()
    return batch


def _get_batch(db, batch_id):
    batch = db.get(TransferBatch, batch_id)
    if not batch:
        raise HTTPException(404, '分段批次不存在')
    return batch


def get_batch(db, batch_id):
    return _get_batch(db, batch_id)


def receive_segment(db, batch_id, data):
    batch = _get_batch(db, batch_id)
    if batch.status not in ACCEPT_SEGMENT_STATUSES:
        raise HTTPException(409, f'批次当前状态为 {batch.status}，不再接收入段（迟到收段不会复活已撤销或已发布批次）')
    if not 0 <= data.segment_index < batch.total_segments:
        raise HTTPException(422, f'段号必须在 0~{batch.total_segments - 1} 之间')
    if len(data.records) != data.row_count:
        raise HTTPException(422, f'段内行数 {len(data.records)} 与登记 row_count {data.row_count} 不一致')
    # 先按契约规范化并做字段校验（含段号/行号定位），再复算段指纹
    records = canonicalize_rows(data.records, segment_index=data.segment_index)
    actual_checksum = checksum(records)
    if actual_checksum != data.checksum.lower():
        # 异文拒收：段指纹与正文不一致，说明传输内容与发送方摘要不符
        raise HTTPException(409, '段校验值与段内容不一致，异文拒收')
    now = time.time()
    existing = db.scalar(
        select(TransferSegment).where(
            TransferSegment.batch_id == batch.id,
            TransferSegment.segment_index == data.segment_index,
        )
    )
    if existing:
        # 同段重试：指纹一致则幂等，不重复计入；指纹不同则异文拒收
        if existing.checksum != actual_checksum:
            raise HTTPException(409, f'第 {data.segment_index} 段已按不同内容登记，异文拒收，不覆盖已收段')
        batch.updated_at = now
        return {'segment_index': existing.segment_index, 'duplicate': True, 'checksum': existing.checksum,
                'row_count': existing.row_count, 'received_at': existing.received_at}
    segment = TransferSegment(
        batch_id=batch.id, segment_index=data.segment_index, row_count=data.row_count,
        checksum=actual_checksum, records=data.records, received_at=now,
    )
    db.add(segment)
    batch.updated_at = now
    try:
        db.flush()
    except Exception:
        # 并发同段上传：唯一约束兜底，转为幂等/异文判定
        db.rollback()
        batch = _get_batch(db, batch_id)
        if batch.status not in ACCEPT_SEGMENT_STATUSES:
            raise HTTPException(409, '批次状态已变更，该段被拒绝')
        existing = db.scalar(
            select(TransferSegment).where(
                TransferSegment.batch_id == batch.id,
                TransferSegment.segment_index == data.segment_index,
            )
        )
        if existing and existing.checksum == actual_checksum:
            return {'segment_index': existing.segment_index, 'duplicate': True, 'checksum': existing.checksum,
                    'row_count': existing.row_count, 'received_at': existing.received_at}
        raise HTTPException(409, f'第 {data.segment_index} 段已按不同内容登记，异文拒收，不覆盖已收段')
    return {'segment_index': segment.segment_index, 'duplicate': False, 'checksum': actual_checksum,
            'row_count': segment.row_count, 'received_at': now}


def _received_indices(db, batch_id):
    return set(db.scalars(
        select(TransferSegment.segment_index).where(TransferSegment.batch_id == batch_id)
    ).all())


def _ordered_segments(db, batch_id):
    return list(db.scalars(
        select(TransferSegment).where(TransferSegment.batch_id == batch_id)
        .order_by(TransferSegment.segment_index)
    ))


def _structural_check(db, batch):
    """齐备性与整批校验，返回问题清单；不改变状态。"""
    problems = []
    received = _received_indices(db, batch.id)
    expected = set(range(batch.total_segments))
    missing = sorted(expected - received)
    if missing:
        problems.append({'code': 'missing_segments', 'message': f'缺少 {len(missing)} 个段',
                         'missing_segments': missing[:ISSUE_SAMPLE_LIMIT], 'missing_total': len(missing)})

    segments = _ordered_segments(db, batch.id)
    received_rows = sum(s.row_count for s in segments)
    if received_rows != batch.total_rows:
        problems.append({'code': 'row_total_mismatch',
                         'message': f'已收行数 {received_rows} 与登记总行数 {batch.total_rows} 不一致',
                         'expected_rows': batch.total_rows, 'actual_rows': received_rows})

    # 跨段（含段内）管号重复定位
    seen, duplicates = {}, []
    for seg in segments:
        for offset, row in enumerate(seg.records):
            sid = row.get('segment_id')
            location = {'segment': seg.segment_index, 'row': offset + 1}
            if sid in seen:
                seen[sid].append(location)
            else:
                seen[sid] = [location]
    dup_items = [{'segment_id': sid, 'occurrences': locs} for sid, locs in seen.items() if len(locs) > 1]
    if dup_items:
        problems.append({'code': 'duplicate_segment_id',
                         'message': f'发现 {len(dup_items)} 个重复管段编号',
                         'duplicates': dup_items[:ISSUE_SAMPLE_LIMIT], 'duplicate_total': len(dup_items)})

    # 字段级校验已在每段接收时完成（canonicalize_rows），此处只做防御性复核并逐条定位
    row_errors = []
    columns = metadata()['columns']
    for seg in segments:
        for offset, row in enumerate(seg.records):
            for c in columns:
                value = row.get(c['key'])
                if value is None or value == '':
                    row_errors.append({'segment': seg.segment_index, 'row': offset + 1,
                                       'field': c['key'], 'message': f'缺少字段 {c["label"]}'})
                elif c['type'] == 'number':
                    try:
                        if isinstance(value, bool) or not _finite_float(value):
                            raise ValueError
                    except (TypeError, ValueError, OverflowError):
                        row_errors.append({'segment': seg.segment_index, 'row': offset + 1,
                                           'field': c['key'], 'message': f'{c["label"]} 必须为有限数值'})
            if isinstance(row.get('segment_id'), (dict, list)) or (
                    row.get('segment_id') is not None and not str(row.get('segment_id')).strip()):
                row_errors.append({'segment': seg.segment_index, 'row': offset + 1,
                                   'field': 'segment_id', 'message': '管段编号不能为空'})
    if row_errors:
        problems.append({'code': 'invalid_rows',
                         'message': f'发现 {len(row_errors)} 处字段问题',
                         'row_errors': row_errors[:ISSUE_SAMPLE_LIMIT], 'row_error_total': len(row_errors)})

    # 整批指纹：按段序拼接全部记录后重算
    if not missing:
        all_records = [row for seg in segments for row in seg.records]
        actual_checksum = checksum(all_records)
        if actual_checksum != batch.batch_checksum:
            problems.append({'code': 'checksum_mismatch',
                             'message': '整批指纹校验失败',
                             'expected_checksum': batch.batch_checksum,
                             'actual_checksum': actual_checksum})
    return problems, missing, received_rows


def _finite_float(value):
    return math.isfinite(float(value))


def confirm_transfer(db, batch_id):
    batch = _get_batch(db, batch_id)
    if batch.status == 'ready':
        return batch  # 幂等确认
    if batch.status != 'collecting':
        raise HTTPException(409, f'批次当前状态为 {batch.status}，无法确认')
    problems, missing, received_rows = _structural_check(db, batch)
    batch.updated_at = time.time()
    if problems:
        # 缺段时仍可补传，保持 collecting；段已齐但内容有问题则失败收口，保留全部已收内容与原因
        batch.issue = {'problems': problems}
        if not missing:
            batch.status = 'failed'
        db.flush()
        raise HTTPException(409, {'message': '批次校验未通过，已保留全部已收内容并定位原因',
                                  'problems': problems})
    batch.status = 'ready'
    batch.issue = {}
    db.flush()
    return batch


def publish_transfer(db, batch_id, expected_checksum=None):
    batch = _get_batch(db, batch_id)
    if expected_checksum and expected_checksum.lower() != batch.batch_checksum:
        raise HTTPException(422, '提交的整批指纹与批次登记指纹不一致')
    if batch.status == 'published':
        # 并发/重试幂等：不重复成批，直接返回既有 Dataset
        dataset = db.get(Dataset, batch.dataset_id)
        return batch, dataset, True
    if batch.status == 'collecting':
        raise HTTPException(409, '批次尚未确认齐备，请先完成确认')
    if batch.status in ('revoking', 'revoked'):
        raise HTTPException(409, '批次已撤销或撤销进行中，发布被拒绝')
    if batch.status == 'failed':
        raise HTTPException(409, '批次整批校验失败，请撤销后重新登记接入')
    if batch.status != 'ready':
        raise HTTPException(409, f'批次当前状态为 {batch.status}，无法发布')
    now = time.time()
    # 条件迁移充当发布锁：与撤销并发时只有一方能赢得状态
    won = db.execute(
        update(TransferBatch)
        .where(TransferBatch.id == batch.id, TransferBatch.status == 'ready')
        .values(status='publishing', updated_at=now)
    ).rowcount == 1
    db.flush()
    if not won:
        db.refresh(batch)
        if batch.status == 'published':
            return batch, db.get(Dataset, batch.dataset_id), True
        raise HTTPException(409, f'批次当前状态为 {batch.status}，发布被拒绝')
    # 发布前再做一次完整防御性校验
    problems, missing, _ = _structural_check(db, batch)
    if problems:
        batch.status = 'failed'
        batch.issue = {'problems': problems}
        db.flush()
        raise HTTPException(409, {'message': '发布前整批校验失败，已保留已收内容并定位原因',
                                  'problems': problems})
    if db.scalar(select(Dataset).where(Dataset.name == batch.name)):
        batch.status = 'ready'
        db.flush()
        raise HTTPException(409, '同名数据批次已存在，无法重复成批')
    segments = _ordered_segments(db, batch.id)
    all_records = [row for seg in segments for row in seg.records]
    dataset = Dataset(name=batch.name, source=batch.source, records=all_records,
                      checksum=batch.batch_checksum, created_at=now)
    db.add(dataset)
    db.flush()
    batch.dataset_id = dataset.id
    batch.status = 'published'
    batch.published_at = now
    batch.updated_at = now
    db.flush()
    return batch, dataset, False


def revoke_transfer(db, batch_id):
    batch = _get_batch(db, batch_id)
    if batch.status == 'revoked':
        return batch, True  # 幂等
    if batch.status == 'published':
        raise HTTPException(409, '批次已发布为完整数据批次，不可撤销')
    if batch.status not in REVOCABLE_STATUSES:
        raise HTTPException(409, f'批次当前状态为 {batch.status}，撤销被拒绝')
    now = time.time()
    won = db.execute(
        update(TransferBatch)
        .where(TransferBatch.id == batch.id, TransferBatch.status.in_(REVOCABLE_STATUSES))
        .values(status='revoking', updated_at=now)
    ).rowcount == 1
    db.flush()
    if not won:
        db.refresh(batch)
        if batch.status == 'revoked':
            return batch, True
        raise HTTPException(409, f'批次当前状态为 {batch.status}，撤销被拒绝')
    db.execute(delete(TransferSegment).where(TransferSegment.batch_id == batch.id))
    batch.status = 'revoked'
    batch.revoked_at = now
    batch.updated_at = now
    batch.issue = {**batch.issue, 'revoked_note': '批次已撤销，已收分段被清理，迟到收段与发布不会复活该批次'}
    db.flush()
    return batch, False


def recover_interrupted(db):
    """进程崩溃兜底：事务回滚后不应残留中间态，这里仅做防御性归一。"""
    for batch in db.scalars(select(TransferBatch).where(TransferBatch.status.in_(('publishing', 'revoking')))):
        if batch.status == 'publishing':
            batch.status = 'ready' if batch.dataset_id is None else 'published'
        else:
            db.execute(delete(TransferSegment).where(TransferSegment.batch_id == batch.id))
            batch.status = 'revoked'
            batch.revoked_at = time.time()
        batch.updated_at = time.time()
    db.commit()


def transfer_dict(db, batch, detail=False):
    received = _received_indices(db, batch.id)
    missing = sorted(set(range(batch.total_segments)) - received)
    received_rows = db.scalar(
        select(func.coalesce(func.sum(TransferSegment.row_count), 0))
        .where(TransferSegment.batch_id == batch.id)
    )
    data = {
        'id': batch.id, 'name': batch.name, 'source': batch.source,
        'total_segments': batch.total_segments, 'total_rows': batch.total_rows,
        'batch_checksum': batch.batch_checksum, 'status': batch.status, 'issue': batch.issue or {},
        'received_segments': len(received), 'received_rows': int(received_rows or 0),
        'missing_segments': missing, 'missing_count': len(missing),
        'dataset_id': batch.dataset_id, 'created_at': batch.created_at,
        'updated_at': batch.updated_at, 'published_at': batch.published_at,
        'revoked_at': batch.revoked_at,
    }
    if detail:
        data['segments'] = [
            {'segment_index': s.segment_index, 'row_count': s.row_count,
             'checksum': s.checksum, 'received_at': s.received_at}
            for s in _ordered_segments(db, batch.id)
        ]
    return data
