"""分段接入的行规范化与字段校验。

契约：上传端（前端 JS）与服务端（Python）先按业务列类型把每行规范化为同一形状，再计算
SHA256（见 utils/checksum.js 与 serialization.checksum），保证两端指纹一致：
- 数值列：接受可转 float 的有限值，统一存为 float（整数也带小数位，JS/Python 文本一致）；
- 字符串列（管段编号）：统一为非空 str；
- bool 不接受为数值；缺失、空串、非有限数值按 422 拒绝，错误带段号与段内行号。
"""
import math
from fastapi import HTTPException
from src.services.business import metadata


def _columns():
    return metadata()['columns']


def canonicalize_rows(records, segment_index=None):
    """就地+返回规范化记录；任何字段问题抛 422（含段/行定位）。"""
    columns = _columns()
    for row_offset, row in enumerate(records):
        location = f'第 {segment_index} 段第 {row_offset + 1} 行' if segment_index is not None else f'第 {row_offset + 1} 行'
        if not isinstance(row, dict):
            raise HTTPException(422, f'{location} 不是有效记录对象')
        for c in columns:
            key = c['key']
            value = row.get(key)
            if value is None or value == '':
                raise HTTPException(422, f'{location} 缺少字段 {c["label"]}')
            if c['type'] == 'number':
                if isinstance(value, bool):
                    raise HTTPException(422, f'{location} {c["label"]} 必须为有限数值')
                try:
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'{location} {c["label"]} 必须为有限数值')
                row[key] = number
            else:
                if isinstance(value, (dict, list)) or not str(value).strip():
                    raise HTTPException(422, f'{location} {c["label"]} 不能为空')
                row[key] = str(value)
    return records
