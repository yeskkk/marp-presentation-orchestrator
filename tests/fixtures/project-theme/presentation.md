---
marp: true
theme: mathist-academic
size: "16:9"
paginate: true
math: mathjax
---
<!-- slide-id: p01-l01-s007 -->
<!-- _class: support -->

## 检验 $(3,1)$：代回每一个原方程

对方程组 $x+y=4,\ x-y=2$，检验同一个 $(3,1)$：

| 原方程 | 代入 | 结果 |
|---|---:|---|
| $x+y=4$ | $3+1=4$ | 成立 |
| $x-y=2$ | $3-1=2$ | 成立 |

两行都成立，所以 $(3,1)\in S$。

只通过一行，或者两行使用不同的数对，都不能得到这个结论。

---
<!-- slide-id: theme-single-image -->
<!-- _class: core -->
## 两条直线的交点

![由方程求出的两条直线及交点](assets/intersection.svg)

交点 $(1,1)$ 同时满足 $x+y=2$ 和 $x-y=0$。

---
<!-- slide-id: theme-display-math -->
<!-- _class: core -->
## 计算结果与每个原条件对应

$$
\begin{aligned}
A\mathbf{x}
&=\begin{bmatrix}1&1\\1&-1\end{bmatrix}
  \begin{bmatrix}3\\1\end{bmatrix}\\
&=\begin{bmatrix}4\\2\end{bmatrix}=\mathbf{b}.
\end{aligned}
$$

**同一个数对**必须同时满足两个条件。

---
<!-- slide-id: theme-markdown-table -->
<!-- _class: core -->
# 三种结果

| 条件的几何关系 | 公共点 | 方程组的解 |
|---|---|---|
| 两条直线相交 | 一个 | 唯一解 |
| 两条不同的直线平行 | 没有 | 无解 |
| 两条直线重合 | 无穷多个 | 无穷多解 |

### 从图形回到原方程

取点后仍需代回原方程。

---
<!-- slide-id: theme-list-and-code -->
<!-- _class: core -->
## 使用同一个数对

1. 把 $x=3$、$y=1$ 代入第一个方程。
2. 再把相同的数对代入第二个方程。
3. **两行均成立**，才能认定它是一个解。

```python
x, y = 3, 1
assert x + y == 4 and x - y == 2
```

