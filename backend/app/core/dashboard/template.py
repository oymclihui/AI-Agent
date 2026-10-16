"""零售经营看板模板（P0 单模板固化）。

- 13 个聚合 SQL：与已实证链路（fa_dash_fetch）同口径，参数化表名。
- REQUIRED_COLUMNS：模板所需列，schema_probe 阶段据此选定数据表。
- ANCHOR_BASELINE：蓝图真值基线（as_of 2026-10-15，数据期间 2026-09-03~10-11）。
  锚点查询按数据内 max(RQ) 所在月与最近 3 天动态计算，与基线偏差 >0.1% 记 warn 并显式披露。
"""
from __future__ import annotations

TEMPLATE_ID = "retail_overview"
TEMPLATE_NAME = "零售经营分析看板"

REQUIRED_COLUMNS = {
    "RQ", "FDBH", "SP_ID", "SPMC", "FL1MC", "FL2MC", "GHDWMC",
    "XSJE", "XSCB", "ML", "YHJE", "ZKJE", "XSSL",
}

# 蓝图第 9 章验收锚点（as_of 2026-10-15 数据快照基线）
ANCHOR_BASELINE = {
    "month_xsje": 2004973.86,   # max(RQ) 所在月销售额
    "month_ml": 285987.4487,    # max(RQ) 所在月毛利
    "recent3_xsje": 491780.90,  # 最近 3 天销售额
    "as_of": "2026-10-15",
}
ANCHOR_TOLERANCE = 0.001  # 相对偏差 0.1%


def build_metric_sqls(table: str) -> dict[str, str]:
    """13 个聚合 SQL（键固定，顺序即取数顺序）。table 已校验为注册表名，不可注入。"""
    t = table
    return {
        # 1. 全期 KPI（净额口径：全行聚合，含退货冲减行）
        "kpi": f"""
SELECT ROUND(SUM(XSJE),2), ROUND(SUM(XSCB),2), ROUND(SUM(ML),4),
       ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,4),
       ROUND(SUM(XSSL),3), ROUND(SUM(ZKJE),2),
       ROUND(SUM(ZKJE)/NULLIF(SUM(XSJE)+SUM(ZKJE),0)*100,4),
       COUNT(*), COUNT(DISTINCT SP_ID), COUNT(DISTINCT RQ),
       ROUND(SUM(YHJE),2)
FROM {t}""",
        # 2. 日趋势
        "daily": f"""
SELECT RQ, ROUND(SUM(XSJE),2), ROUND(SUM(ML),2),
       ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2),
       ROUND(SUM(ZKJE),2), ROUND(SUM(XSSL),1), COUNT(*)
FROM {t} GROUP BY RQ ORDER BY RQ""",
        # 3. 一级品类
        "fl1": f"""
SELECT FL1MC, ROUND(SUM(XSJE),2), ROUND(SUM(ML),2),
       ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2),
       ROUND(SUM(XSSL),1), ROUND(SUM(ZKJE),2), COUNT(DISTINCT SP_ID)
FROM {t} GROUP BY FL1MC ORDER BY SUM(XSJE) DESC""",
        # 4. 二级品类 TOP12（销售额）
        "fl2": f"""
SELECT FL1MC, FL2MC, ROUND(SUM(XSJE),2), ROUND(SUM(ML),2),
       ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2), COUNT(DISTINCT SP_ID)
FROM {t} GROUP BY FL1MC, FL2MC ORDER BY SUM(XSJE) DESC LIMIT 12""",
        # 5. 商品销售额 TOP10
        "top_sp": f"""
SELECT SPMC, FL1MC, ROUND(SUM(XSJE),2), ROUND(SUM(ML),2),
       ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2), ROUND(SUM(XSSL),1)
FROM {t} GROUP BY SPMC, FL1MC ORDER BY SUM(XSJE) DESC LIMIT 10""",
        # 6. 负毛利商品 TOP10
        "neg_sp": f"""
SELECT SPMC, FL1MC, COUNT(*) neg_rows, ROUND(SUM(ML),2) neg_ml, ROUND(SUM(XSJE),2)
FROM {t} WHERE ML < 0
GROUP BY SPMC, FL1MC ORDER BY SUM(ML) ASC LIMIT 10""",
        # 7. 负毛利日趋势
        "neg_daily": f"""
SELECT RQ, COUNT(*) neg_rows, ROUND(SUM(ML),2) neg_ml
FROM {t} WHERE ML < 0 GROUP BY RQ ORDER BY RQ""",
        # 8. 负毛利按一级品类
        "neg_fl1": f"""
SELECT FL1MC, COUNT(*) neg_rows, ROUND(SUM(ML),2) neg_ml, ROUND(SUM(XSJE),2)
FROM {t} WHERE ML < 0 GROUP BY FL1MC ORDER BY SUM(ML) ASC""",
        # 9. 折扣按一级品类
        "zk_fl1": f"""
SELECT FL1MC, ROUND(SUM(ZKJE),2),
       ROUND(SUM(ZKJE)/NULLIF(SUM(XSJE)+SUM(ZKJE),0)*100,2)
FROM {t} GROUP BY FL1MC ORDER BY SUM(ZKJE) DESC""",
        # 10. 毛利额 TOP10 二级类
        "fl2_ml": f"""
SELECT FL1MC, FL2MC, ROUND(SUM(ML),2), ROUND(SUM(XSJE),2),
       ROUND(SUM(ML)/NULLIF(SUM(XSJE),0)*100,2)
FROM {t} GROUP BY FL1MC, FL2MC ORDER BY SUM(ML) DESC LIMIT 10""",
        # 11. 周几分析
        "dow": f"""
SELECT DAYNAME(RQ) dow, ROUND(SUM(XSJE),2), ROUND(SUM(ML),2), COUNT(DISTINCT RQ) days
FROM {t} GROUP BY DAYNAME(RQ)""",
        # 12. 供应商 TOP8
        "supplier": f"""
SELECT GHDWMC, ROUND(SUM(XSJE),2), ROUND(SUM(ML),2), COUNT(DISTINCT SP_ID)
FROM {t} WHERE GHDWMC IS NOT NULL AND GHDWMC <> ''
GROUP BY GHDWMC ORDER BY SUM(XSJE) DESC LIMIT 8""",
        # 13. 锚点：max(RQ) 所在月销售额/毛利 + 最近 3 天销售额（与基线比对）
        "anchor": f"""
SELECT
  (SELECT ROUND(SUM(XSJE),2) FROM {t}
    WHERE DATE_FORMAT(RQ,'%Y-%m')=(SELECT DATE_FORMAT(MAX(RQ),'%Y-%m') FROM {t})) AS month_xsje,
  (SELECT ROUND(SUM(ML),4) FROM {t}
    WHERE DATE_FORMAT(RQ,'%Y-%m')=(SELECT DATE_FORMAT(MAX(RQ),'%Y-%m') FROM {t})) AS month_ml,
  (SELECT ROUND(SUM(XSJE),2) FROM {t}
    WHERE RQ >= DATE_SUB((SELECT MAX(RQ) FROM {t}), INTERVAL 2 DAY)) AS recent3_xsje,
  (SELECT MAX(RQ) FROM {t}) AS max_rq,
  (SELECT MIN(RQ) FROM {t}) AS min_rq
""",
    }
