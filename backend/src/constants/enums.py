from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class TransferStatus(str, Enum):
    collecting = 'collecting'   # 收段中
    ready = 'ready'             # 齐备待发布（尚未通过完整字段校验）
    publishing = 'publishing'   # 发布进行中（崩溃恢复依据）
    published = 'published'     # 已发布为完整 Dataset
    revoking = 'revoking'       # 撤销进行中
    revoked = 'revoked'         # 已撤销
    failed = 'failed'           # 整批校验失败，保留已收内容
