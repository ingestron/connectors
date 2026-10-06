"""Reviewed portable temporal values: exact dates and unzoned microsecond timestamps."""
import re
from datetime import date,datetime

MESSAGES={
    'TEMPORAL_DATE':'DATE requires a valid calendar date in YYYY-MM-DD format; review the source field or contract mapping.',
    'TEMPORAL_TIMESTAMP':'TIMESTAMP requires a valid full calendar date and time; review the source field or contract mapping.',
    'TEMPORAL_TIMEZONE':'TIMESTAMP requires a timezone-less value; review an explicit timezone mapping before ingestion.',
    'TEMPORAL_PRECISION':'Source timestamp precision exceeds six fractional digits; review an exact precision mapping before ingestion.',
    'TEMPORAL_TYPE':'Select a supported reviewed temporal type.',
}

class TemporalError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(MESSAGES[code])

def temporal_value(value,kind):
    """Exact calendar date or timezone-less microsecond timestamp; never round/guess."""
    if kind=='date':
        if type(value) is date:return value
        if not isinstance(value,str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
            raise TemporalError('TEMPORAL_DATE')
        try:return date.fromisoformat(value)
        except ValueError:raise TemporalError('TEMPORAL_DATE') from None
    if kind!='timestamp':raise TemporalError('TEMPORAL_TYPE')
    if type(value) is datetime:
        if value.tzinfo is not None:raise TemporalError('TEMPORAL_TIMEZONE')
        return value
    if not isinstance(value,str) or len(value)>128:raise TemporalError('TEMPORAL_TIMESTAMP')
    base=r'[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}'
    if re.fullmatch(base+r'(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})',value):
        raise TemporalError('TEMPORAL_TIMEZONE')
    match=re.fullmatch(base+r'(?:\.([0-9]+))?',value)
    if match is None:raise TemporalError('TEMPORAL_TIMESTAMP')
    if match[1] is not None and len(match[1])>6:raise TemporalError('TEMPORAL_PRECISION')
    try:return datetime.fromisoformat(value)
    except ValueError:raise TemporalError('TEMPORAL_TIMESTAMP') from None
