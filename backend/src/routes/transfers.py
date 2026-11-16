from fastapi import APIRouter, Depends
from sqlalchemy import select
from src.config.database import get_db
from src.models import TransferBatch
from src.schemas.transfer import TransferOpenInput, TransferSegmentInput, TransferPublishInput
from src.middlewares.auth import current_user, can_write
from src.services import transfer as service
from src.services.audit import record
router = APIRouter(prefix='/transfers')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    batches = db.scalars(select(TransferBatch).order_by(TransferBatch.id.desc()).limit(100))
    return [service.transfer_dict(db, b) for b in batches]


@router.post('', status_code=201)
def open_batch(data: TransferOpenInput, db=Depends(get_db), u=Depends(can_write)):
    b = service.open_transfer(db, data, u)
    record(db, u.email, 'transfer.open',
           {'id': b.id, 'total_segments': b.total_segments, 'total_rows': b.total_rows})
    db.commit()
    return service.transfer_dict(db, b, detail=True)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    return service.transfer_dict(db, service.get_batch(db, id), detail=True)


@router.post('/{id}/segments', status_code=200)
def add_segment(id: int, data: TransferSegmentInput, db=Depends(get_db), u=Depends(can_write)):
    result = service.receive_segment(db, id, data)
    record(db, u.email, 'transfer.segment',
           {'id': id, 'segment': result['segment_index'], 'duplicate': result['duplicate'],
            'rows': result['row_count']})
    db.commit()
    return result


@router.post('/{id}/confirm')
def confirm(id: int, db=Depends(get_db), u=Depends(can_write)):
    try:
        b = service.confirm_transfer(db, id)
    except Exception:
        # 校验失败时服务端已写入失败原因/状态，先持久化再把问题返回调用方
        db.commit()
        raise
    record(db, u.email, 'transfer.confirm', {'id': id, 'status': b.status})
    db.commit()
    return service.transfer_dict(db, b, detail=True)


@router.post('/{id}/publish', status_code=201)
def publish(id: int, data: TransferPublishInput | None = None,
            db=Depends(get_db), u=Depends(can_write)):
    b, dataset, reused = service.publish_transfer(db, id, getattr(data, 'expected_checksum', None))
    if not reused:
        record(db, u.email, 'transfer.publish', {'id': id, 'dataset_id': dataset.id, 'rows': len(dataset.records)})
    db.commit()
    return {'batch': service.transfer_dict(db, b), 'dataset_id': dataset.id, 'reused': reused}


@router.post('/{id}/revoke')
def revoke(id: int, db=Depends(get_db), u=Depends(can_write)):
    b, reused = service.revoke_transfer(db, id)
    if not reused:
        record(db, u.email, 'transfer.revoke', {'id': id})
    db.commit()
    return service.transfer_dict(db, b)
