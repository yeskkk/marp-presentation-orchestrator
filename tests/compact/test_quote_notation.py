import pytest
from mpres.control.quote_evidence import quoted_evidence_present as present


def test_numeric_column_and_typographic_transpose():
    assert present('$p=(100,50)^T$', r'$p=(100,50)^{\mathsf T}$')
    assert present('$(6,-1)^T$', r'$$x=\begin{bmatrix}6\\-1\end{bmatrix}.$$')
    assert present(r'$\begin{bmatrix}6\\-1\end{bmatrix}$', '$(6,-1)^T$')


@pytest.mark.parametrize('quote', ['$(6,1)^T$', '$(-1,6)^T$', '$(6,-2)^T$',
                                  '$(6,-1)$', '$(61)^T$', '$(6,-1)^t$'])
def test_column_equivalence_preserves_values_order_and_transpose(quote):
    assert not present(quote, r'$\begin{bmatrix}6\\-1\end{bmatrix}$')


def test_no_row_matrix_symbolic_or_plain_text_rewriting():
    assert not present('$(6,-1)^T$', r'$\begin{bmatrix}6&-1\end{bmatrix}$')
    assert not present('$(a,b)^T$', r'$\begin{bmatrix}a\\b\end{bmatrix}$')
    assert not present('(6,-1)^T', r'\begin{bmatrix}6\\-1\end{bmatrix}')
    assert not present('AB=I', 'BA=I')


def test_paired_strong_emphasis_keeps_words_and_negation():
    assert present('零空间（齐次方程组的解空间）','**零空间**（齐次方程组的解空间）')
    assert not present('零空间（齐次方程组的解空间）','**列空间**（齐次方程组的解空间）')
    assert not present('结论：一定可逆','结论：**不一定**可逆')
