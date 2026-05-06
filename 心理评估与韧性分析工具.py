# -*- coding: utf-8 -*-
# ==============================================================================
# 软件名称：心理评估与韧性分析工具
# 版本：V1.0
# 开发者：Li Yutong
# 研发机构：延边大学
# 描述：基于 Streamlit 和 SQLite 开发的科研辅助测评脚本工具。
# 包含 CTQ、CD-RISC、RRS 三大量表的数字化录入、T分数转换及加权风险预警。
# ==============================================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sqlite3
import logging
import base64
from datetime import datetime

# ==============================================================================
# 1. 全局配置与基准数据 (Config & Norms)
# ==============================================================================

# 配置简易运行日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 本地数据库路径
DB_PATH = "psych_tool_data.db"

# 常模基线参数库：用于将原始分转化为标准 T 分数
NORM_DATA = {
    "中国成人常模(2025)": {
        "CTQ": {"mean": 38.5, "std": 14.2},
        "CD-RISC": {"mean": 65.4, "std": 16.2},
        "RRS": {"mean": 42.8, "std": 11.5}
    },
    "大学生常模(2024)": {
        "CTQ": {"mean": 41.2, "std": 15.0},
        "CD-RISC": {"mean": 68.1, "std": 14.8},
        "RRS": {"mean": 45.3, "std": 12.1}
    },
    "临床干预参考线": {
        "CTQ": {"mean": 55.0, "std": 12.5},
        "CD-RISC": {"mean": 48.5, "std": 18.2},
        "RRS": {"mean": 58.7, "std": 10.4}
    }
}

# ==============================================================================
# 2. 数据库操作模块 (DBManager)
# ==============================================================================

class DBManager:
    """处理 SQLite 数据库存储和后台查询逻辑"""
    
    @staticmethod
    def init_db():
        """初始化工具的本地数据库表结构"""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        uid TEXT NOT NULL,
                        norm_type TEXT,
                        raw_ctq INTEGER, raw_risc INTEGER, raw_rrs INTEGER,
                        t_ctq REAL, t_risc REAL, t_rrs REAL,
                        risk_level TEXT,
                        report_content TEXT,
                        create_time DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                logging.info("SQLite 表结构检测/初始化完成")
        except Exception as e:
            logging.error(f"DB Init Error: {e}")

    @staticmethod
    def insert_record(data):
        """插入单条受测者记录"""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                sql = """
                    INSERT INTO records (
                        uid, norm_type, raw_ctq, raw_risc, raw_rrs,
                        t_ctq, t_risc, t_rrs, risk_level, report_content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                cursor.execute(sql, (
                    data['uid'], data['norm_type'], 
                    data['raw_ctq'], data['raw_risc'], data['raw_rrs'],
                    data['t_ctq'], data['t_risc'], data['t_rrs'], 
                    data['risk_level'], data['report']
                ))
                conn.commit()
                return True
        except Exception as e:
            logging.error(f"Insert Record Error: {e}")
            return False

    @staticmethod
    def get_all_records():
        """提取全量数据供科研导出"""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                return pd.read_sql("SELECT * FROM records ORDER BY create_time DESC", conn)
        except Exception as e:
            logging.error(f"Query Error: {e}")
            return pd.DataFrame()

# ==============================================================================
# 3. 业务算法层 (Calculator & RiskEvaluator)
# ==============================================================================

class ScoreCalculator:
    """核心算法：处理原始分到 T 分数的标准化映射"""
    
    @staticmethod
    def get_t_score(raw_score, scale_name, norm_name):
        try:
            params = NORM_DATA[norm_name][scale_name]
            # 统计学公式：T = 50 + 10 * Z
            z_score = (raw_score - params["mean"]) / params["std"]
            t_score = 50 + (10 * z_score)
            return round(t_score, 2)
        except KeyError:
            logging.warning(f"常模缺失: {norm_name}-{scale_name}，抛出默认值 50")
            return 50.0

class RiskEvaluator:
    """风险判定：基于三维特征的加权评估"""
    
    @staticmethod
    def evaluate(t_ctq, t_risc, t_rrs):
        # 判定公式：创伤和反刍是加分项，韧性是减分(保护)项，+15平滑基数
        risk_score = (t_ctq * 0.4) + (t_rrs * 0.4) - (t_risc * 0.3) + 15
        
        # 风险层级路由
        if risk_score >= 65:
            level = "高风险"
            color = "red"
            desc = "预警：早期创伤负荷较高，反刍思维明显，且当前韧性资源严重不足。建议及时干预。"
        elif risk_score >= 50:
            level = "中风险"
            color = "orange"
            desc = "提示：处于亚健康心理状态，存在一定压力，需注意情绪调节以防反刍思维加重。"
        else:
            level = "低风险"
            color = "green"
            desc = "安全：心理状态稳定，韧性资源能够有效缓冲生活压力。"
            
        return {
            "score": round(risk_score, 2),
            "level": level,
            "color": color,
            "desc": desc
        }

# ==============================================================================
# 4. 静态题库矩阵 (Scale Data)
# 包含量表完整题干与反向计分(rev)标识
# ==============================================================================

class ScaleRepository:
    
    @staticmethod
    def get_ctq():
        # CTQ-28 童年不良经历问卷
        return [
            {"id": 1, "q": "我觉得我由一个对自己非常有爱的人抚养长大", "dim": "情感忽视", "rev": True},
            {"id": 2, "q": "我小时候家里有人说了一些让我伤心或感到羞辱的话", "dim": "情感虐待", "rev": False},
            {"id": 3, "q": "我感觉我小时候家里人经常互相帮助", "dim": "情感忽视", "rev": True},
            {"id": 4, "q": "我感觉我小时候家里人很照顾我", "dim": "情感忽视", "rev": True},
            {"id": 5, "q": "我小时候家里有人踢过我、抓过我或扇过我耳光", "dim": "躯体虐待", "rev": False},
            {"id": 6, "q": "我小时候有足够的东西吃", "dim": "躯体忽视", "rev": True},
            {"id": 7, "q": "我小时候家里有人打过我，甚至留下了淤青或伤痕", "dim": "躯体虐待", "rev": False},
            {"id": 8, "q": "我小时候家里有人碰过我的私处或要求我碰他们的私处", "dim": "性虐待", "rev": False},
            {"id": 9, "q": "我小时候家里有人咒骂过我或羞辱过我", "dim": "情感虐待", "rev": False},
            {"id": 10, "q": "我小时候有人曾经强迫我做一些性行为", "dim": "性虐待", "rev": False},
            {"id": 11, "q": "我小时候家里有人打我打得我不得不去看医生或去医院", "dim": "躯体虐待", "rev": False},
            {"id": 12, "q": "我小时候家里有人使我觉得我是家里一个特殊或重要的人", "dim": "情感忽视", "rev": True},
            {"id": 13, "q": "我小时候家里有人在我的身体上留下伤痕或伤迹", "dim": "躯体虐待", "rev": False},
            {"id": 14, "q": "我觉得我家里的人彼此深爱着对方", "dim": "情感忽视", "rev": True},
            {"id": 15, "q": "我小时候家里有人说一些令我讨厌的话", "dim": "情感虐待", "rev": False},
            {"id": 16, "q": "我小时候家里有人使我觉得我没人要或家里不需要我", "dim": "情感虐待", "rev": False},
            {"id": 17, "q": "我小时候家里有人强迫我去看性方面的照片或电影", "dim": "性虐待", "rev": False},
            {"id": 18, "q": "我小时候家里有人做了一些性方面的事或说了一些性方面的话", "dim": "性虐待", "rev": False},
            {"id": 19, "q": "我觉得我家里的人相互关心", "dim": "情感忽视", "rev": True},
            {"id": 20, "q": "我小时候家里有人打得我浑身淤青", "dim": "躯体虐待", "rev": False},
            {"id": 21, "q": "我小时候家里有人猥亵我", "dim": "性虐待", "rev": False},
            {"id": 22, "q": "我小时候家里有人使我觉得我是个累赘", "dim": "情感虐待", "rev": False},
            {"id": 23, "q": "我小时候家里有人照顾我，并保护我的安全", "dim": "躯体忽视", "rev": True},
            {"id": 24, "q": "我小时候家里有人让顾我觉得我很丑或一无是处", "dim": "情感虐待", "rev": False},
            {"id": 25, "q": "我小时候有人尝试强迫我与其发生性行为", "dim": "性虐待", "rev": False},
            {"id": 26, "q": "我小时候家里有人穿的衣服很脏", "dim": "躯体忽视", "rev": False},
            {"id": 27, "q": "我小时候家里有人酒后打我", "dim": "躯体虐待", "rev": False},
            {"id": 28, "q": "我小时候家里有人疏于照顾我", "dim": "躯体忽视", "rev": False}
        ]

    @staticmethod
    def get_risc():
        # CD-RISC-25 心理韧性量表 (全正向)
        return [
            {"id": 1, "q": "我能够适应改变", "dim": "坚韧性"},
            {"id": 2, "q": "我有一个亲近的朋友可以支持我", "dim": "自强性"},
            {"id": 3, "q": "当我遇到挫折时，我能很快恢复过来", "dim": "乐观性"},
            {"id": 4, "q": "我觉得我有能力应对生活中发生的事情", "dim": "坚韧性"},
            {"id": 5, "q": "即使事情看起来很糟糕，我也能找到解决办法", "dim": "自强性"},
            {"id": 6, "q": "即使遇到重重困难，我仍能达到目标", "dim": "坚韧性"},
            {"id": 7, "q": "在压力下我能保持冷静", "dim": "坚韧性"},
            {"id": 8, "q": "我倾向于从积极的角度看待事物", "dim": "乐观性"},
            {"id": 9, "q": "我为自己的成就感到自豪", "dim": "自强性"},
            {"id": 10, "q": "我是一个坚强的人", "dim": "坚韧性"},
            {"id": 11, "q": "我不容易被困难吓倒", "dim": "坚韧性"},
            {"id": 12, "q": "即使面对压力，我仍然能全神贯注", "dim": "坚韧性"},
            {"id": 13, "q": "我喜欢挑战新事物", "dim": "自强性"},
            {"id": 14, "q": "我相信自己能掌控生活", "dim": "乐观性"},
            {"id": 15, "q": "我对自己有信心", "dim": "自强性"},
            {"id": 16, "q": "我有明确的人生奋斗目标", "dim": "自强性"},
            {"id": 17, "q": "我是一个乐观的人", "dim": "乐观性"},
            {"id": 18, "q": "我对自己所做的事情有责任感", "dim": "坚韧性"},
            {"id": 19, "q": "我觉得生活是有意义的", "dim": "乐观性"},
            {"id": 20, "q": "我相信自己能处理不确定性", "dim": "坚韧性"},
            {"id": 21, "q": "我能很快从打击中恢复", "dim": "坚韧性"},
            {"id": 22, "q": "我不会被失败击垮", "dim": "坚韧性"},
            {"id": 23, "q": "我认为自己是一个有韧性的人", "dim": "自强性"},
            {"id": 24, "q": "我能找到克服困难的方法", "dim": "坚韧性"},
            {"id": 25, "q": "我擅长在困难中发现机遇", "dim": "乐观性"}
        ]

    @staticmethod
    def get_rrs():
        # RRS-22 反刍思维量表 (全正向)
        return [
            {"id": 1, "q": "我会不停地想自己感到多么难过", "dim": "症状反刍"},
            {"id": 2, "q": "我会不停地思考自己的疲劳和身体不适", "dim": "症状反刍"},
            {"id": 3, "q": "我会想：‘我为什么会这样？’", "dim": "强迫思考"},
            {"id": 4, "q": "我会想：‘要是当时没那样做就好了’", "dim": "强迫思考"},
            {"id": 5, "q": "我会反复分析最近发生的事情来寻找原因", "dim": "反省深思"},
            {"id": 6, "q": "我会写下自己的感受并进行深入思考", "dim": "反省深思"},
            {"id": 7, "q": "我会想自己目前处境多么糟糕", "dim": "症状反刍"},
            {"id": 8, "q": "我会独自坐着思考自己的感受", "dim": "症状反刍"},
            {"id": 9, "q": "我会反复思考自己为什么感觉这么糟", "dim": "强迫思考"},
            {"id": 10, "q": "我会想：‘我没心情做任何事’", "dim": "症状反刍"},
            {"id": 11, "q": "我会想：‘我永远也无法摆脱这些感觉’", "dim": "症状反刍"},
            {"id": 12, "q": "我会分析自己的性格缺陷", "dim": "反省深思"},
            {"id": 13, "q": "我会想：‘如果我不能振作起来，后果会很严重’", "dim": "强迫思考"},
            {"id": 14, "q": "我会思考自己有多么孤独", "dim": "症状反刍"},
            {"id": 15, "q": "我会想：‘为什么我处理事情这么糟糕？’", "dim": "强迫思考"},
            {"id": 16, "q": "我会想：‘我再也受不了了’", "dim": "症状反刍"},
            {"id": 17, "q": "我会反复回忆过去不愉快的事", "dim": "强迫思考"},
            {"id": 18, "q": "我会通过思考来试图理解我的抑郁", "dim": "反省深思"},
            {"id": 19, "q": "我会思考生活中的一切都变得不如意", "dim": "症状反刍"},
            {"id": 20, "q": "我会分析导致我不开心的原因", "dim": "反省深思"},
            {"id": 21, "q": "我会思考自己无法集中注意力的现状", "dim": "症状反刍"},
            {"id": 22, "q": "我会想：‘为什么只有我这么痛苦？’", "dim": "强迫思考"}
        ]

# ==============================================================================
# 5. 前端图表与组件 (UI Utils)
# ==============================================================================

def draw_radar(t_ctq, t_risc, t_rrs, color_code):
    """构建多维雷达图"""
    categories = ['CTQ(创伤负荷)', 'RISC(心理韧性)', 'RRS(认知反刍)', '抗压能力评估', '情绪稳定性']
    
    # 辅助节点：社会表现和情绪稳定（平滑雷达图多边形）
    social_score = max(30, t_risc * 1.1)
    emotion_score = max(30, 100 - t_rrs)
    
    values = [t_ctq, t_risc, t_rrs, social_score, emotion_score]
    values.append(values[0]) # 闭合绘图路径
    categories.append(categories[0])
    
    color_map = {
        "red": ("rgba(231, 76, 60, 0.5)", "#C0392B"),
        "orange": ("rgba(243, 156, 18, 0.4)", "#D35400"),
        "green": ("rgba(44, 62, 80, 0.4)", "#2C3E50")
    }
    fill_color, line_color = color_map.get(color_code, color_map["green"])

    fig = go.Figure(go.Scatterpolar(
        r=values, theta=categories, fill='toself',
        fillcolor=fill_color, line=dict(color=line_color, width=2)
    ))
    
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False, margin=dict(l=40, r=40, t=40, b=40)
    )
    return fig

def get_csv_download_link(df):
    """Pandas DF 转 CSV 下载链接"""
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="export_psych_data.csv" style="padding: 8px 12px; background-color: #4CAF50; color: white; border-radius: 4px; text-decoration: none;">📥 导出历史测评数据 (CSV)</a>'

# ==============================================================================
# 6. 工具主入口 (Main Tool Engine)
# ==============================================================================

def main():
    st.set_page_config(page_title="心理评估与韧性分析工具", layout="wide", page_icon="📝")
    DBManager.init_db()

    # 坑：必须用 session_state 保存提交后的状态，不然切 tab 就清空了
    if 'record_data' not in st.session_state:
        st.session_state.record_data = None
    
    # --- 侧边栏配置区 ---
    with st.sidebar:
        st.title("工具配置参数")
        input_uid = st.text_input("受测者编号 (UID)", "U-1001")
        selected_norm = st.selectbox("对标常模数据库", list(NORM_DATA.keys()))
        
        st.divider()
        st.write("操作提示：请依次完成右侧量表后点击提交。")

    st.title("心理评估与韧性分析工具 (V1.0)")

    tab_test, tab_report, tab_admin = st.tabs(["📝 问卷录入", "📊 诊断分析", "📂 数据导出"])

    # ---------- Tab 1: 问卷录入 ----------
    with tab_test:
        st.info("注意：工具后台会自动处理部分题目的反向计分逻辑。")
        
        with st.expander("录入模块一：CTQ 童年经历 (28题)"):
            st.write("1=从不，2=很少，3=有时，4=经常，5=总是")
            ctq_scores = []
            for item in ScaleRepository.get_ctq():
                val = st.slider(f"{item['id']}. {item['q']}", 1, 5, 3, key=f"ctq_{item['id']}")
                # 反向计分 (6 - x)
                ctq_scores.append((6 - val) if item['rev'] else val)
            
        with st.expander("录入模块二：CD-RISC 心理韧性 (25题)"):
            st.write("1=完全不符合，2=较少符合，3=有点符合，4=较多符合，5=完全符合")
            risc_scores = []
            for item in ScaleRepository.get_risc():
                val = st.radio(f"{item['id']}. {item['q']}", [1, 2, 3, 4, 5], index=2, horizontal=True, key=f"risc_{item['id']}")
                risc_scores.append(val)
                
        with st.expander("录入模块三：RRS 反刍思维 (22题)"):
            st.write("1=从不，2=有时，3=经常，4=总是")
            rrs_scores = []
            for item in ScaleRepository.get_rrs():
                val = st.radio(f"{item['id']}. {item['q']}", [1, 2, 3, 4], index=1, horizontal=True, key=f"rrs_{item['id']}")
                rrs_scores.append(val)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("提交录入数据并执行运算", type="primary"):
            sum_ctq, sum_risc, sum_rrs = sum(ctq_scores), sum(risc_scores), sum(rrs_scores)
            
            # 计算标准 T 分
            t_c = ScoreCalculator.get_t_score(sum_ctq, "CTQ", selected_norm)
            t_r = ScoreCalculator.get_t_score(sum_risc, "CD-RISC", selected_norm)
            t_s = ScoreCalculator.get_t_score(sum_rrs, "RRS", selected_norm)
            
            # 执行风险测算
            eval_res = RiskEvaluator.evaluate(t_c, t_r, t_s)
            
            # 数据封装
            record = {
                'uid': input_uid, 'norm_type': selected_norm,
                'raw_ctq': sum_ctq, 'raw_risc': sum_risc, 'raw_rrs': sum_rrs,
                't_ctq': t_c, 't_risc': t_r, 't_rrs': t_s,
                'risk_level': eval_res['level'],
                'color_code': eval_res['color'],
                'report': eval_res['desc']
            }
            
            if DBManager.insert_record(record):
                st.session_state.record_data = record
                st.success("运算完成！数据已入库，请前往【诊断分析】查看雷达图。")
            else:
                st.error("入库失败，请检查 SQLite 读写权限。")

    # ---------- Tab 2: 诊断分析 ----------
    with tab_report:
        if not st.session_state.record_data:
            st.warning("暂无数据，请先在左侧 Tab 完成录入。")
        else:
            data = st.session_state.record_data
            st.subheader(f"综合特征画像 - 档案: {data['uid']}")
            
            if data['color_code'] == 'red':
                st.error(f"机器判定等级：{data['risk_level']}")
            elif data['color_code'] == 'orange':
                st.warning(f"机器判定等级：{data['risk_level']}")
            else:
                st.success(f"机器判定等级：{data['risk_level']}")
                
            c1, c2, c3 = st.columns(3)
            c1.metric("CTQ 创伤负荷 (T分)", data['t_ctq'])
            c2.metric("CD-RISC 韧性效能 (T分)", data['t_risc'])
            c3.metric("RRS 反刍偏向 (T分)", data['t_rrs'])
            
            fig = draw_radar(data['t_ctq'], data['t_risc'], data['t_rrs'], data['color_code'])
            st.plotly_chart(fig, use_container_width=True)
            
            st.markdown("### 系统判定结论")
            st.write(data['report'])

    # ---------- Tab 3: 数据导出 ----------
    with tab_admin:
        st.subheader("本地数据管理库")
        df = DBManager.get_all_records()
        
        if not df.empty:
            st.dataframe(df[['id', 'uid', 'norm_type', 't_ctq', 't_risc', 't_rrs', 'risk_level', 'create_time']], use_container_width=True)
            st.markdown(get_csv_download_link(df), unsafe_allow_html=True)
        else:
            st.write("本地数据库暂无存量数据。")

if __name__ == "__main__":
    main()