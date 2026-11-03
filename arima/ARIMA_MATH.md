# ARIMA: what do p, d and q do?

Imagine a rain gauge recording a five-minute rainfall total $y_t$ at each time
step $t$. ARIMA predicts future values using patterns in the **past readings**
and past **surprises**: the differences between what it predicted and what
was observed.

Our code first transforms rainfall to reduce the influence of large values:

$$
z_t = \log(1+y_t)
$$

## The general model: ARIMA(p, d, q)

First, $d$ determines which series the model works with. Write that series as
$w_t$:

| $d$ | What the model uses |
|---|---|
| 0 | The transformed rainfall itself: $w_t=z_t$ |
| 1 | Its change: $w_t=z_t-z_{t-1}$ |
| 2 | The change in that change: $w_t=(z_t-z_{t-1})-(z_{t-1}-z_{t-2})$ |

Then $p$ and $q$ determine **how much history** appears in the equation:

$$
w_t = c
+ \underbrace{\sum_{i=1}^{p}\phi_i w_{t-i}}_{\text{p previous values}}
+ \varepsilon_t
+ \underbrace{\sum_{j=1}^{q}\theta_j\varepsilon_{t-j}}_{\text{q previous surprises}}
$$

Here $\varepsilon_t$ is the new surprise, $c$ is an optional constant, and
$\phi_i$ and $\theta_j$ are weights estimated from the data.

- If **$p=2$**, the first sum uses $w_{t-1}$ and $w_{t-2}$: two previous
  values. If $p=0$, it uses none.
- If **$q=2$**, the second sum uses $\varepsilon_{t-1}$ and
  $\varepsilon_{t-2}$: two previous surprises. If $q=0$, it uses none.
- **$d$ controls what those $w$ values represent**: levels, changes, or
  changes in changes. It is not a weight learned from the data.

More history is not automatically better, and more differencing is not always
appropriate. Compare small choices on held-out data rather than assuming
larger numbers will improve forecasts.

## Our model: ARIMA(1,1,1)

We set $d=1$, so $w_t=\Delta z_t=z_t-z_{t-1}$. With $p=1$ and $q=1$,
the equation becomes:

$$
\Delta z_t
= \underbrace{\phi_1\Delta z_{t-1}}_{\text{one previous change}}
+ \varepsilon_t
+ \underbrace{\theta_1\varepsilon_{t-1}}_{\text{one previous surprise}}
$$

The current implementation uses **no drift term**. For intuition, suppose the
last change was $0.1$, the last surprise was $0.2$, and the fitted weights
were $\phi_1=0.5$ and $\theta_1=0.25$. The model's predicted *next change*
is $0.5(0.1)+0.25(0.2)=0.1$ on the **log-transformed scale**; the future
surprise is unknown and has zero expected contribution. These numbers are
illustrative, not fitted results.

## From model to canoeing forecast

The [implementation](__main__.py) fits `(1, 1, 1)` to recent observations,
forecasts forward, converts each prediction back with
$\max(0,\exp(\hat z)-1)$, and sums the five-minute amounts in the trip
window. For example, with the last observation at **14:00**, it predicts 30
steps through 16:30, skips the six before 14:30, and sums the remaining 24.
The default “rain” threshold is 0.1 mm for that total—not a probability.

This model sees rainfall at one location only, so it cannot see an approaching
shower. It has not yet been validated on real KNMI data here. See the
[technical report](TECHNICAL_REPORT.md) for data and evaluation details.
