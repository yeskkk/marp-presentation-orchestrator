"""Conservative format matching shared by all review evidence consumers.

Never normalize numbers, signs, negation, or identifier spelling.
Within paired math only, recognize typographic transpose T and numeric column
vectors written as a transposed tuple. Other internal TeX stays literal.
Token boundaries distinguish `1 2` from `12`. Only actual math delimiters,
whitespace layout and one terminal sentence delimiter are ignored.
"""
import re
import unicodedata

TOKEN = re.compile(r'\\[A-Za-z]+|\d+(?:\.\d+)?|[A-Za-z]+|[^\s]')
END = frozenset('.。;；:：,，!！?？')


def math_notation(match):
    text=match.group(1)
    text=re.sub(r'\^\{\\mathsf\s*\{?T\}?\}', '^T', text)
    number=r'[+-]?\d+(?:\.\d+)?'
    column=re.compile(r'\\begin\{bmatrix\}\s*('+number+r'(?:\s*\\\\\s*'+number+r')+)\s*\\end\{bmatrix\}')
    def tuple_form(m):
        return '\\numericcolumn{'+','.join(x.strip() for x in m.group(1).split('\\\\'))+'}'
    text=column.sub(tuple_form,text)
    transposed=re.compile(r'\(\s*('+number+r'(?:\s*,\s*'+number+r')+)\s*\)\s*\^T')
    return transposed.sub(lambda m:'\\numericcolumn{'+','.join(x.strip() for x in m.group(1).split(','))+'}',text)


def tokens(text: str) -> tuple[str,...]:
    text=unicodedata.normalize('NFC',text)
    # Paired Markdown strong emphasis changes presentation, not quoted words.
    text=re.sub(r'(?<!\*)\*\*(?!\*)([^\n]+?)(?<!\*)\*\*(?!\*)',r'\1',text)
    # Strip paired unescaped delimiters only; a currency dollar is not math syntax.
    text=re.sub(r'(?<!\\)\$\$(.+?)(?<!\\)\$\$',math_notation,text,flags=re.S)
    text=re.sub(r'(?<!\\)\$(?!\$)(.+?)(?<!\\)\$',math_notation,text,flags=re.S)
    text=re.sub(r'\\\((.*?)\\\)',math_notation,text,flags=re.S)
    text=re.sub(r'\\\[(.*?)\\\]',math_notation,text,flags=re.S)
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
