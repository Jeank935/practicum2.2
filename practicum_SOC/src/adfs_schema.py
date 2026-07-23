"""Esquema confirmado del origen ADFS sin encabezados."""

SOURCE_COLUMNS = [
    "id",
    "event_name",
    "log_source",
    "event_count",
    "event_time",
    "created_at",
    "updated_at",
    "event_id",
    "low_level_category",
    "source_ip",
    "destination_ip",
    "username",
    "custom_user_id",
    "custom_ip_address",
    "custom_relying_party",
    "custom_message",
    "event_type_id",
    "event_time_origen",
]

EVENT_DEFINITIONS = {
    "Application Token Success": ("1200", "success"),
    "Fresh Credential Validation Error": ("1203", "failure"),
    "Extranet Lockout Audit": ("1210", "lockout"),
}
