## 实验结果记录

### 实验设计

#### 1.全面优化
testrunner:epoch 0
devloop->testrunner all:epoch 1
devloop->testrunner all:epoch 2
...

#### 2.单样本迭代优化
对一张图，单独用ask_ai记录基础评分
用dev_loop。。。

### 实验结果
#### 1.基线
|code| task | Compile rate | Avg compile attempts|Critic pass rate | Avg fidelity score |
|---|------|-------------|------------------|-------------------|-------------------|
v1|easy|100%|1.0|90.0%|3.4/5.0|
v2|easy|100%|1.0|84.0%%|3.24/5.0|
v1|medium|
v1|difficult|
v1||chart/plot|
v1|math formula|
v1|math geometry|
v1|pure drawing|100.0%|1.0|82.0%|3.05/5.0




#### 2.全面优化结果
每轮一次dev_loop
|task|epoch| Compile rate | Avg compile attempts|Critic pass rate | Avg fidelity score |
|-----|----|----|--|--|--|
easy|0|100%|1.0|84.0%|3.24/5.0|
easy|1|100%|1.0|84.0%|3.39/5.0|
easy|2|100%|1.0|94.0%|3.50/5.0|
medium|0|100%|1.0|60.0%|2.69/5.0|
medium|1|100%|1.0|96.0%|3.04/5.0|
medium|2|100%|1.0|84.0%|2.89/5.0|
difficult|0|100%|1.0|58.0%|2.91/5.0|
difficult|1|100%|1.0|78.0%|2.70/5.0|
difficult|2|100%|1.0|48.0%|2.67/5.0|
chart_plot|0|100%|1.0|84.0%|2.92/5.0|
chart_plot|1|100%|1.0|72.0%|3.21/5.0|
chart_plot|2|100%|1.0|86.0%|3.22/5.0|
pure_drawing|0|100%|1.0|76.9%|2.85/5.0|
pure_drawing|1|100%|1.0|53.8%|2.77/5.0|
pure_drawing|1|100%|1.0|69.2%|2.88/5.0|
math_geometry|0|100%|1.0|64.0%|2.55/5.0|
math_geometry|1|100%|1.0|78.0%|2.75/5.0|
math_geometry|2|100%|1.0|50.0%|2.66/5.0
math_formula|0|100%|1.0|89.3%|2.89/5.0|
math_formula|1|100%|1.0|82.1%|2.84/5.0|
math_formula|2|100%|1.0|82.1%|2.84/5.0|
math_formula|3|100%|1.0|92.9%|3.09/5.0|


0
3.5
1
3.5
2
4.0 pass

#### 3.单张图优化结果
挑了difficult/0030.png尝试一下.

- difficult/0030.png
|epoch|score(askai)|score(devloop)
0|4.0|3.5|
1|2.0|3.5|
2|2.5|2.5|
3|3.5|3.5|
4|3.5|3.5|


- medium/0017.png
|epoch|score(askai)|score(devloop)
0|3.5|3.5|
1|2.0|4.0|

- easy/0023.png
|epoch|score(askai)|score(devloop)
0|2.5|2.5|
1|2.0|2.0|
2|2.0|


#### 针对medium优化
保存在txt里
把result记录发给deepseek手动优化结果
|task|epoch| Compile rate | Avg compile attempts|Critic pass rate | Avg fidelity score |
|-----|----|----|--|--|--|
|medium|0|100%|1.0|60.0%|2.69/5.0|
|medium|1|100%|1.0|68.0%|2.88/5.0|
|medium|2|100%|1.0|66.0%|2.95/5.0|
|medium|3|100%|1.0|86.0%|2.95/5.0|

用medium的prompt跑easy:
|easy|0|100%|1.0|74.0%|3.37/5.0|