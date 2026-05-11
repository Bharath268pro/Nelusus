"""Salesforce data models"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class SalesforceRecord(BaseModel):
    """Base model for any Salesforce record"""

    id: str = Field(..., description="Salesforce record ID")
    type: str = Field(..., description="Salesforce object type")
    created_date: Optional[datetime] = Field(None, description="Record creation date")
    last_modified_date: Optional[datetime] = Field(None, description="Last modification date")
    attributes: Dict[str, Any] = Field(default={}, description="Additional attributes")


class SalesforceAccount(SalesforceRecord):
    """Salesforce Account object"""

    name: str = Field(..., description="Account name")
    industry: Optional[str] = Field(None, description="Industry")
    revenue: Optional[float] = Field(None, description="Annual revenue")
    website: Optional[str] = Field(None, description="Website URL")
    phone: Optional[str] = Field(None, description="Phone number")
    billing_street: Optional[str] = Field(None, description="Billing street address")
    billing_city: Optional[str] = Field(None, description="Billing city")
    billing_state: Optional[str] = Field(None, description="Billing state")
    billing_country: Optional[str] = Field(None, description="Billing country")
    billing_postal_code: Optional[str] = Field(None, description="Billing postal code")
    owner_id: Optional[str] = Field(None, description="Owner user ID")
    parent_account_id: Optional[str] = Field(None, description="Parent account ID")
    custom_fields: Dict[str, Any] = Field(default={}, description="Custom field values")


class SalesforceContact(SalesforceRecord):
    """Salesforce Contact object"""

    first_name: str = Field(..., description="First name")
    last_name: str = Field(..., description="Last name")
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    mobile_phone: Optional[str] = Field(None, description="Mobile phone number")
    account_id: Optional[str] = Field(None, description="Associated account ID")
    title: Optional[str] = Field(None, description="Job title")
    department: Optional[str] = Field(None, description="Department")
    custom_fields: Dict[str, Any] = Field(default={}, description="Custom field values")


class SalesforceError(BaseModel):
    """Salesforce API error response"""

    error_code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    fields: Optional[list[str]] = Field(None, description="Fields that caused the error")
