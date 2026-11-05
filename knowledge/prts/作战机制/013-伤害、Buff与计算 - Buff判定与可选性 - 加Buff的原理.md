---
title: PRTS · 作战机制 · 伤害、Buff与计算 / Buff判定与可选性 / 加Buff的原理
category: 机制
tags:
- 作战机制
- 索敌
- 仇恨
- 阻挡
- 伤害
- 战斗
- 伤害、Buff与计算 / Buff判定与可选性 / 加Buff的原理
source: https://prts.wiki/w/%E4%BD%9C%E6%88%98%E6%9C%BA%E5%88%B6#%E5%8A%A0Buff%E7%9A%84%E5%8E%9F%E7%90%86
updated: '2026-10-17'
server: PRTS 中文站页面；页面涉及的服务器、版本和修正说明以正文为准
license: CC BY-NC-SA 4.0
license_url: https://creativecommons.org/licenses/by-nc-sa/4.0/
fetched_at: '2026-11-05T15:46:41+08:00'
revision_id: '441625'
original_title: 作战机制
attribution: PRTS Wiki 页面贡献者；贡献者历史见原站；游戏原始素材权利归原权利人
extraction_note: 正文抽取、表格转带列名记录、按章节拆分；Rank I/II/III 规范为专精一/二/三；未用模型补写。图片、范围图、视频及交互计算器未转录。抓取时间不是资料适用版本。
---

# PRTS · 作战机制 · 伤害、Buff与计算 / Buff判定与可选性 / 加Buff的原理

理论参考：

隐身，又岂止是无敌，舟游判定的那点事

在2020年3月17日的更新之前，明日方舟中给某个范围内的单位加Buff的原理如下：

技能开启、有常驻性Buff的干员部署时，通过 Buff选择器 选中攻击范围内所有能选择的目标。

在Buff生效期间新单位进入生效区域时通过 Buff选择器 试图选中新单位并加Buff。

单位离开生效区域，技能结束或干员退场时强制清除目标身上的对应Buff。 由于这个兜底机制的存在，大部分光环类buff持续时间都是永久。

其他情况下基本不更新Buff状态。

在2020年3月17日的更新之后，Buff判定机制发生了一定的修改，但原机制仍然绝大部分有效，后文用到时会标注出已经更改的部分。
