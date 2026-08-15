from pydantic import BaseModel, Field, field_validator
from typing import Optional
import datetime

class DailyPriceContract(BaseModel):
    trade_date: str = Field(..., description="YYYY-MM-DD")
    stock_id: str = Field(..., min_length=4, max_length=6)
    stock_name: str
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(..., ge=0)
    turnover: float = Field(..., ge=0)
    market_type: str = Field(..., description="TWSE or TPEx")

    @field_validator("trade_date")
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.date.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError("trade_date must be in YYYY-MM-DD format")

    @field_validator("stock_id")
    @classmethod
    def validate_stock_id(cls, v):
        if not v.isalnum():
            raise ValueError("stock_id must be alphanumeric")
        return str(v)

class InstitutionalFlowContract(BaseModel):
    trade_date: str
    stock_id: str
    # Enforce Optional[float] = None to avoid hiding missing data with zero (B-02 compliance)
    foreign_net_buy: Optional[float] = Field(None, description="Units: Shares or TWD")
    investment_trust_net_buy: Optional[float] = Field(None)
    dealer_net_buy: Optional[float] = Field(None)

    @field_validator("trade_date")
    @classmethod
    def validate_date(cls, v):
        datetime.date.fromisoformat(v)
        return v

class MarginTradingContract(BaseModel):
    trade_date: str
    stock_id: str
    margin_buy: Optional[float] = Field(None)
    margin_sell: Optional[float] = Field(None)
    margin_balance: Optional[float] = Field(None)
    short_buy: Optional[float] = Field(None)
    short_sell: Optional[float] = Field(None)
    short_balance: Optional[float] = Field(None)

    @field_validator("trade_date")
    @classmethod
    def validate_date(cls, v):
        datetime.date.fromisoformat(v)
        return v

class CautionDispositionContract(BaseModel):
    trade_date: str
    stock_id: str
    status: str
    disposition_period: int = 0

class StockIndustryMappingContract(BaseModel):
    stock_id: str
    stock_name: str
    primary_sector: str
    secondary_sector: Optional[str] = None
    theme_1: Optional[str] = None
    theme_2: Optional[str] = None
    theme_3: Optional[str] = None
    supply_chain_role: Optional[str] = None
    valid_from: str
    valid_to: Optional[str] = None
    reviewed: int = 0
