"""Old Uzbek Latin letters mapped to the new single letters."""
_MARKS=("'",'‘','’','ʻ','ʼ','`','´','′','ʹ')

def to_new(value):
    if not isinstance(value,str) or not value:return value
    text=value
    for mark in _MARKS:
        text=text.replace('G'+mark,'Ğ').replace('g'+mark,'ğ').replace('O'+mark,'Ö').replace('o'+mark,'ö')
    return text.replace('SH','Ş').replace('Sh','Ş').replace('sh','ş').replace('CH','Ç').replace('Ch','Ç').replace('ch','ç')

def fold(value):
    text=to_new(value if isinstance(value,str) else '' if value is None else str(value)).lower()
    text=text.replace('ö','o').replace('ğ','g').replace('ş','sh').replace('ç','ch')
    for mark in _MARKS:text=text.replace(mark,'')
    return ' '.join(text.split())
