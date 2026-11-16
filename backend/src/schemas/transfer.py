from pydantic import BaseModel, Field

class TransferOpenInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='night-patrol.upload', max_length=200)
    total_segments: int = Field(ge=1, le=10000)
    total_rows: int = Field(ge=5, le=2_000_000)
    batch_checksum: str = Field(min_length=32, max_length=64)

class TransferSegmentInput(BaseModel):
    segment_index: int = Field(ge=0)
    row_count: int = Field(ge=1, le=100000)
    checksum: str = Field(min_length=32, max_length=64)
    records: list[dict] = Field(min_length=1, max_length=100000)

class TransferPublishInput(BaseModel):
    expected_checksum: str | None = Field(default=None, min_length=32, max_length=64)
