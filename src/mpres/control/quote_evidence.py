"""Conservative format matching shared by all review evidence consumers.

Never normalize numbers, signs, negation, identifier spelling, or internal TeX.
Token boundaries distinguish `1 2` from `12`. Only actual math delimiters,
whitespace layout and one terminal sentence delimiter are ignored.
"""
import re
import unicodedata

TOKEN = re.compile(r'\\[A-Za-z]+|\d+(?:\.\d+)?|[A-Za-z]+|[^\s]')
END = frozenset('.。;；:：,，!！?？')


def tokens(text: str) -> tuple[str,...]:
    text=unicodedata.normalize('NFC',text)
    # Strip paired unescaped delimiters only; a currency dollar is not math syntax.
    text=re.sub(r'(?<!\\)\$\$(.+?)(?<!\\)\$\$',r'\1',text,flags=re.S)
    text=re.sub(r'(?<!\\)\$(?!\$)(.+?)(?<!\\)\$',r'\1',text,flags=re.S)
    text=re.sub(r'\\\((.*?)\\\)',r'\1',text,flags=re.S)
    text=re.sub(r'\\\[(.*?)\\\]',r'\1',text,flags=re.S)
    return tuple(TOKEN.findall(text))


def quoted_evidence_present(quote: str, source: str) -> bool:
    if not isinstance(quote,str) or not isinstance(source,str) or not quote.strip():return False
    needle=tokens(quote);hay=tokens(source)
    if not needle:return False
    def contains(seq):
        return any(hay[i:i+len(seq)]==seq for i in range(len(hay)-len(seq)+1))
    if contains(needle):return True
    if len(needle)>1 and needle[-1] in END:
        base=needle[:-1]
        return any(hay[i:i+len(base)]==base and i+len(base)<len(hay) and hay[i+len(base)] in END
                   for i in range(len(hay)-len(base)))
    return False
