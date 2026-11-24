"""本文件实现普通法律咨询 Agent，负责法律问答的检索、推理与引用校验。"""

from __future__ import annotations

from datetime import date
import re

from agent_service.prompts import get_prompt

from .base import BaseAgent


class LawQaAgent(BaseAgent):
    """面向普通法律咨询的业务 Agent。"""

    agent_key = "law_qa"
    agent_name = "法律咨询"

    _TRAFFIC_SCENARIO_TERMS = (
        "行政处罚 交通违法记分 罚款 驾驶证吊销 终生禁驾 "
        "民事赔偿 交强险 商业三者险 责任比例 "
        "交通肇事罪 入罪标准 死亡 重伤 财产损失 逃逸 量刑 "
        "不构成犯罪 不会坐牢 常见误区 积极救助 主动报警 "
        "赔偿损失 取得谅解 自首 认罪认罚 从宽 缓刑"
    )

    _TRAFFIC_MEDICAL_EXPENSE_TERMS = (
        "交通事故 受害人医疗费 医疗保险 医保报销 第三人侵权 "
        "中华人民共和国社会保险法第三十条 应当由第三人负担 第三人不支付或者无法确定第三人 基本医疗保险基金先行支付 追偿 "
        "中华人民共和国道路交通安全法第七十五条 第七十六条 抢救费用 "
        "交强险 医疗费用赔偿限额 商业第三者责任险 侵权人赔偿 责任比例"
    )

    _SELF_DEFENSE_BOUNDARY_TERMS = (
        "正当防卫 构成要件 不法侵害 正在进行 防卫意图 防卫对象 "
        "防卫必要限度 明显超过必要限度 重大损害 防卫过当 "
        "互殴认定 斗殴故意 侵害结束后反击 报复行为 特殊防卫"
    )

    _TERMINATION_COMPENSATION_TERMS = (
        "解除劳动合同 经济补偿 N N+1 代通知金 违法解除赔偿金 2N "
        "协商一致解除 无过失性辞退 经济性裁员 员工过错辞退 "
        "劳动合同法第三十九条 第四十条 第四十六条 第四十七条 第四十八条 第八十七条 "
        "工作年限 月工资 前十二个月平均工资 工资三倍封顶 继续履行劳动合同"
    )

    _WAGE_ARREARS_REMEDY_TERMS = (
        "拖欠工资 欠薪 工资支付 劳动法第五十条 劳动合同法第三十条 第三十八条 第四十六条 第八十五条 "
        "工资支付暂行规定 劳动争议调解仲裁法第五条 第二十七条 "
        "固定证据 劳动关系证明 工资标准 银行流水 工资条 考勤记录 欠薪沟通记录 书面催告 送达凭证 "
        "劳动监察投诉 12333 支付令 劳动仲裁 仲裁时效 起诉期限 强制执行 "
        "拖欠工资本金 解除劳动合同经济补偿 加付赔偿金50%至100% 加班费 未签劳动合同二倍工资 "
        "不要擅自旷工 被迫解除通知 离职原因 个人原因辞职 工资已结清 和解协议 权利保留 拒不支付劳动报酬罪"
    )

    _WAGE_ARREARS_AMOUNT_TERMS = (
        "拖欠工资本金 工资支付周期 月工资 欠薪月数 应付工资 实发工资 工资条 银行流水 "
        "中华人民共和国劳动法第五十条 劳动合同法第三十条 第八十五条 "
        "欠薪本金与经济补偿分别计算 经济补偿触发条件 加付赔偿金前置程序 "
        "不得重复计算 N N+1 2N"
    )

    _WAGE_ARREARS_RECOVERY_TERMS = (
        "只追讨拖欠工资 最短维权路径 书面欠薪确认 催款通知 送达凭证 "
        "劳动保障监察投诉 12333 支付令 劳动争议仲裁 仲裁请求拖欠工资本金 "
        "劳动合同法第三十条 第八十五条 劳动争议调解仲裁法第五条 第二十七条 "
        "工资条 银行流水 考勤记录 在职证明 解除通知 举证责任 仲裁时效 强制执行"
    )

    _LABOR_ARBITRATION_LIMITATION_TERMS = (
        "劳动争议调解仲裁法第二十七条 劳动争议申请仲裁时效一年 "
        "劳动关系存续期间拖欠劳动报酬不受一年限制 劳动关系终止后一年内提出 "
        "仲裁时效中断 重新计算 主张权利 请求权利救济 同意履行义务 "
        "离职日期 欠薪 工资报酬 劳动仲裁申请书 管辖仲裁委员会 线上立案 "
        "工资本金 加班费 未休年休假工资 未签劳动合同二倍工资 经济补偿 条件式主张 "
        "紧急立案 先提交基础材料 后补充证据 送达记录 银行流水 工资条 考勤记录"
    )

    _DOCUMENT_TEMPLATE_TERMS = (
        "正式示范文本 完整合同结构 当事人信息 房屋基本状况 租赁用途 "
        "租赁期限 交付 返还 租金 押金 费用承担 房屋维修 装饰装修 "
        "转租 提前解除 合同解除 违约责任 争议解决 通知送达 附件 签字盖章"
    )

    _PLEADING_TEMPLATE_TERMS = (
        "民事起讼状(借贷纠纷) 民事起诉状 民间借贷纠纷 借款合同 贷款 欠款 原告 被告 "
        "诉讼请求 本金 利息 逾期利息 律师费 保全费 诉讼费 "
        "事实与理由 管辖法院 证据目录 附件清单 起诉状副本 签字盖章"
    )

    _CIVIL_FILING_TERMS = (
        "最高人民法院关于人民法院登记立案若干问题的规定 中华人民共和国民事诉讼法 "
        "民事起诉状 原告身份证明 被告身份信息 证据材料 证据目录 "
        "起诉状副本 被告人数 相符份数 法院留存 送达地址确认书 管辖依据 "
        "授权委托书 代理人身份证明 现场立案 网上立案 人民法院在线服务 诉讼费"
    )

    _LIMITATION_PERIOD_TERMS = (
        "中华人民共和国民法典第一百八十八条 诉讼时效期间三年 知道或者应当知道权利受损害 "
        "中华人民共和国民法典第一百九十五条 诉讼时效中断 重新计算 请求履行义务 同意履行义务 提起诉讼 "
        "最高人民法院关于审理民事案件适用诉讼时效制度若干问题的规定 "
        "民间借贷 约定还款日期 履行期限届满次日 未约定还款日期 宽限期届满次日 "
        "首次催款 明确拒绝还款 最长权利保护期间二十年 起算点 中断证据"
    )

    _LEASE_REPAIR_TERMS = (
        "房屋租赁 承租人 出租人 房东 漏水 渗水 维修义务 "
        "中华人民共和国民法典第七百一十二条 第七百一十三条 "
        "出租人履行维修义务 承租人请求合理期限内维修 出租人未履行维修义务 "
        "承租人自行维修 维修费用出租人负担 影响使用 减少租金 延长租期 "
        "书面维修通知 微信聊天记录 送达证据 漏水照片视频 物业排查 维修票据 "
        "严重影响居住 合同解除 违约责任 租赁合同维修条款"
    )

    _LEASE_REPAIR_NOTICE_TERMS = (
        "房屋租赁 漏水维修 出租人维修义务 民法典第七百一十二条 第七百一十三条 "
        "三次催告 书面维修通知 微信聊天记录 电子数据 原始载体 完整上下文 身份对应 "
        "送达凭证 出租人收到通知 经催告仍不维修 自行维修 维修费用 减少租金"
    )

    _LEASE_REPAIR_TIMELINE_TERMS = (
        "房屋租赁 漏水维修 催修通知 时间线 第一次催修 第二次催修 第三次催修 "
        "通知日期 送达日期 微信聊天记录 维修请求 出租人收到通知 经催告仍未维修"
    )

    _LEASE_REPAIR_FACT_UPDATE_TERMS = (
        "房屋租赁 漏水维修 承租人 出租人 房东 当事人姓名 案件事实补充"
    )

    _LEASE_REPAIR_DAMAGE_TERMS = (
        "房屋租赁 漏水导致电脑损坏 财产损失 电脑维修费 维修发票 因果关系 "
        "出租人维修义务 违约损害赔偿 可预见损失 减损义务 实际损失 维修明细"
    )

    _RENOVATION_CONTRACT_TERMS = (
        "房屋装饰装修合同 装修工程 施工合同 工期延误 逾期完工 继续履行 合同解除 "
        "民法典第五百六十三条 第五百七十七条 第五百八十二条 第五百八十三条 "
        "第八百零一条 第八百零二条 第八百零三条 质量不合格 修理 返工 改建 "
        "工程价款结算 已完工程量 折价鉴定 逾期违约金 实际损失 临时租房损失 "
        "防水渗漏 第三方检测报告 现状保全 楼下邻居损失 不可抗力 工人不足 商业风险"
    )

    _LEASE_REPAIR_RECAP_TERMS = (
        "房屋租赁 漏水维修 多次催修 出租人仍未维修 电脑损坏 维修费发票 "
        "财产损失赔偿 维修费用 减少租金 解除合同 押金返还 剩余租金结算"
    )

    _LEASE_REPAIR_TERMINATION_TERMS = (
        "房屋租赁 漏水 卧室无法居住 合同目的不能实现 法定解除 单方解除 "
        "民法典第五百六十三条 第五百六十五条 第七百一十二条 第七百一十三条 "
        "第七百二十九条 第七百三十一条 出租人经催告仍不维修 危及安全健康 "
        "解除通知 到达生效 退房交接 损失赔偿"
    )

    _LEASE_REPAIR_SETTLEMENT_TERMS = (
        "房屋租赁 合法解除后果 押金返还 剩余预付租金 按实际居住天数结算 "
        "民法典第五百六十六条 第五百七十七条 合同解除恢复原状 采取补救措施 赔偿损失 "
        "押金扣除项目 水电燃气物业费 承租人损坏 举证责任 退房交接清单 "
        "解除通知送达日期 租赁终止日期 租金结算明细 返还期限"
    )

    @staticmethod
    def _current_user_query(state) -> str:
        return str(state.get("original_query") or state.get("query") or "").strip()

    def _labor_intent(self, state) -> str:
        """识别劳动子意图；专项规则只允许由本轮用户原话触发。"""
        current = self._current_user_query(state)
        history = str(state.get("history_summary") or "")
        memory = state.get("legal_memory") or {}
        if hasattr(memory, "model_dump"):
            memory = memory.model_dump(mode="json")
        case = dict((memory or {}).get("current_case") or {})

        termination_event = any(word in current for word in ("辞退", "裁员", "开除", "解除劳动合同", "违法解除", "被迫离职"))
        compensation_ask = any(word in current for word in ("补偿", "赔偿", "赔多少", "多少钱", "N+1", "2N", "代通知金"))
        if termination_event and compensation_ask:
            return "termination_compensation"

        arbitration_focus = any(word in current for word in ("仲裁", "时效", "还来得及", "还能申请", "离职", "去年", "前年"))
        wage_context = case.get("labor_dispute_topic") == "wage_arrears" or any(
            word in history for word in ("拖欠工资", "欠薪", "工资没发", "工资未发")
        )
        arbitration_context = case.get("labor_arbitration_question") or "仲裁" in history
        if arbitration_focus and (wage_context or arbitration_context):
            return "labor_arbitration_limitation"

        recovery_only = wage_context and any(word in current for word in (
            "只想先追回工资", "只追工资", "先追回工资", "追回工资", "拿回工资", "要回工资",
        ))
        if recovery_only:
            return "wage_arrears_recovery"

        arrears_period_added = bool(re.search(
            r"(?:拖欠|欠|没发|未发)[^，。；;？！?\n]{0,8}[一二两三四五六七八九十\d]+\s*个?月(?:工资)?",
            current,
        ))
        if wage_context and arrears_period_added:
            return "wage_arrears_amount"

        if (
            "欠薪" in current
            or "拖欠工资" in current
            or ("工资" in current and any(word in current for word in ("没发", "未发", "不发", "不给", "没给", "克扣", "少发")))
        ):
            return "wage_arrears_remedy"
        return ""

    def _traffic_intent(self, state) -> str:
        """仅识别交通事故医疗费/保险追问，避免污染其他保险咨询。"""
        current = self._current_user_query(state)
        medical_ask = any(word in current for word in (
            "医疗保险", "医保", "医疗费", "医药费", "治疗费", "住院费", "抢救费",
        )) and any(word in current for word in ("赔", "报", "付", "承担", "能不能", "可以吗"))
        if not medical_ask:
            return ""

        history = str(state.get("history_summary") or "")
        memory = state.get("legal_memory") or {}
        if hasattr(memory, "model_dump"):
            memory = memory.model_dump(mode="json")
        case = dict((memory or {}).get("current_case") or {})
        traffic_context = case.get("event_type") == "交通事故" or any(
            word in history for word in ("交通事故", "开车撞", "撞到了", "交警认定", "电动车", "交强险")
        )
        return "traffic_medical_expense" if traffic_context else ""

    def _loan_limitation_intent(self, state) -> str:
        """识别民间借贷时效连续追问，并区分事实回忆与法律分析。"""
        current = self._current_user_query(state)
        history = str(state.get("history_summary") or "")
        memory = state.get("legal_memory") or {}
        if hasattr(memory, "model_dump"):
            memory = memory.model_dump(mode="json")
        case = dict((memory or {}).get("current_case") or {})
        if case.get("civil_dispute_topic") == "residential_lease_repair":
            return ""
        user_history = "\n".join(
            line for line in history.splitlines() if line.strip().startswith("用户：")
        ) or history
        loan_context = case.get("civil_dispute_topic") == "private_lending" or any(
            word in user_history for word in ("借给朋友", "借条", "借款", "欠钱不还", "还款日期")
        )
        if not loan_context:
            return ""

        fact_questions = ("多少钱", "多少元", "还款日期吗", "显示还款日期", "有说过要还", "记得吗")
        if any(word in current for word in fact_questions):
            return "loan_fact_recall"
        interruption_terms = ("微信", "承认欠", "确认欠", "承诺", "答应", "年底一定还", "重新算", "重新计算")
        due_date_terms = ("借条写", "还款日期", "前还款", "到期")
        limitation_terms = ("诉讼时效", "什么时候必须起诉", "多久必须起诉", "最晚起诉", "一直不还")
        if any(word in current for word in interruption_terms):
            return "loan_limitation_interruption"
        if any(word in current for word in due_date_terms):
            return "loan_limitation_due_date"
        if any(word in current for word in limitation_terms):
            return "loan_limitation_general"
        return ""

    def _lease_repair_intent(self, state) -> str:
        """识别租赁漏水维修及省略主语的催告证据追问。"""
        current = self._current_user_query(state)
        history = str(state.get("history_summary") or "")
        memory = state.get("legal_memory") or {}
        if hasattr(memory, "model_dump"):
            memory = memory.model_dump(mode="json")
        case = dict((memory or {}).get("current_case") or {})
        # 已确认的装修合同主题具有排他性；装修延期产生的“临时租房”和装修
        # 质量问题中的“漏水”绝不能触发房屋租赁维修专项提示词。
        if case.get("civil_dispute_topic") == "renovation_contract":
            return ""
        user_history = "\n".join(
            line for line in history.splitlines() if line.strip().startswith("用户：")
        ) or history
        rental_context = case.get("civil_dispute_topic") == "residential_lease_repair" or (
            any(word in user_history for word in ("租的房子", "租房", "房东"))
            and any(word in user_history for word in ("漏水", "渗水", "不维修", "不修"))
        )
        if not rental_context:
            return ""
        if re.search(
            r"第\s*[一二两三四五六七八九十\d]+\s*次(?:催修|催告|通知|联系)?\s*"
            r"(?:是|在|为)?\s*(?:今年)?\s*(?:(?:20\d{2})\s*年)?\s*\d{1,2}\s*月\s*\d{1,2}\s*日",
            current,
        ):
            return "lease_repair_notice_timeline"
        if re.fullmatch(r"\s*房东(?:叫|是|姓名为?)\s*[^，。；;？！?\s]{1,12}[。.]?\s*", current):
            return "lease_repair_fact_update"
        if any(word in current for word in ("之前说的", "房东叫什么", "催修了几次", "电脑损失是多少")):
            return "lease_repair_case_recap"
        damage_fact_patterns = (
            r"\s*(?:漏水|渗水)[^，。；;？！?\n]{0,12}(?:导致|造成)[^，。；;？！?\n]{0,8}电脑(?:损坏|进水|故障)[。.]?\s*",
            r"\s*电脑(?:维修|修理)(?:花了|花费|费用(?:是|为)?|费(?:是|为)?)?\s*\d+(?:\.\d+)?\s*元[。.]?\s*",
            r"\s*(?:我)?(?:有|也有|还有)维修发票[。.]?\s*",
        )
        if any(re.fullmatch(pattern, current) for pattern in damage_fact_patterns):
            return "lease_repair_damage_update"
        if re.fullmatch(
            r"\s*(?:房东|出租人)[^，。；;？！?\n]{0,12}(?:不修|不维修|一直没修|一直没有维修|仍未维修)[。.]?\s*",
            current,
        ) or re.fullmatch(r"\s*(?:我)?(?:也)?有?[一二两三四五六七八九十\d]+次催修记录[。.]?\s*", current):
            return "lease_repair_fact_update"
        if any(word in current for word in ("押金", "剩余租金", "预付租金", "退租金", "返还租金")):
            return "lease_repair_settlement"
        if any(word in current for word in ("解除合同", "解除租赁", "退租", "无法居住", "不能居住", "住不了")):
            return "lease_repair_termination"
        if any(word in current for word in ("催过", "通知过", "联系过", "微信聊天记录", "聊天记录")):
            return "lease_repair_notice_evidence"
        if any(word in current for word in ("漏水", "渗水", "维修", "不修", "房东")):
            return "lease_repair_remedy"
        return ""

    def _renovation_contract_intent(self, state) -> str:
        """识别装修合同长对话，优先依赖已锁定的结构化主题。"""
        current = self._current_user_query(state)
        memory = state.get("legal_memory") or {}
        if hasattr(memory, "model_dump"):
            memory = memory.model_dump(mode="json")
        case = dict((memory or {}).get("current_case") or {})
        if case.get("civil_dispute_topic") != "renovation_contract":
            return ""
        if any(word in current for word in ("前面的对话", "直接根据", "总结", "我有哪些证据", "主要主张")):
            return "renovation_case_recap"
        if any(word in current for word in ("工人不足", "不可抗力", "理由成立")):
            return "renovation_force_majeure"
        if any(word in current for word in ("解除合同", "返还多收", "返还工程款", "返工费", "临时租房费")):
            return "renovation_termination_settlement"
        if any(word in current for word in ("漏水", "渗水", "防水", "楼下", "检测报告", "返工")):
            return "renovation_quality_damage"
        return "renovation_followup"

    def _retrieval_query(self, state):
        """为事实型交通问题补齐责任维度，避免只召回原则性条文。"""
        if state.get("targeted_labor_fallback"):
            return (
                "中华人民共和国劳动争议调解仲裁法 第二十七条 "
                "劳动争议申请仲裁时效一年 劳动关系终止 拖欠劳动报酬 一年内提出"
            )
        query = super()._retrieval_query(state)
        current = self._current_user_query(state)
        normalized = current.replace("起讼状", "起诉状")
        labor_intent = self._labor_intent(state)
        traffic_intent = self._traffic_intent(state)
        loan_intent = self._loan_limitation_intent(state)
        lease_intent = self._lease_repair_intent(state)
        renovation_intent = self._renovation_contract_intent(state)
        if traffic_intent == "traffic_medical_expense":
            memory = state.get("legal_memory") or {}
            if hasattr(memory, "model_dump"):
                memory = memory.model_dump(mode="json")
            case = dict((memory or {}).get("current_case") or {})
            known_facts = " ".join(
                f"{key}={case[key]}" for key in (
                    "event_type", "user_vehicle_type", "counterparty_vehicle_type",
                    "liability", "counterparty_injury_description", "escaped", "drunk_driving",
                ) if key in case
            )
            return f"{current} {known_facts} {self._TRAFFIC_MEDICAL_EXPENSE_TERMS}".strip()
        if labor_intent == "labor_arbitration_limitation":
            memory = state.get("legal_memory") or {}
            if hasattr(memory, "model_dump"):
                memory = memory.model_dump(mode="json")
            case = dict((memory or {}).get("current_case") or {})
            facts = " ".join(str(case.get(key) or "") for key in ("labor_dispute_topic", "employment_end_date_text"))
            return f"{current} {facts} {self._LABOR_ARBITRATION_LIMITATION_TERMS}".strip()
        if labor_intent == "wage_arrears_remedy":
            return f"{current} {self._WAGE_ARREARS_REMEDY_TERMS}"
        if labor_intent in ("wage_arrears_amount", "wage_arrears_recovery"):
            memory = state.get("legal_memory") or {}
            if hasattr(memory, "model_dump"):
                memory = memory.model_dump(mode="json")
            case = dict((memory or {}).get("current_case") or {})
            fact_keys = ("monthly_salary_yuan", "work_years", "wage_arrears_months", "employment_ended")
            facts = " ".join(f"{key}={case[key]}" for key in fact_keys if case.get(key) is not None)
            terms = self._WAGE_ARREARS_AMOUNT_TERMS if labor_intent == "wage_arrears_amount" else self._WAGE_ARREARS_RECOVERY_TERMS
            return f"{current} {facts} {terms}".strip()
        if labor_intent == "termination_compensation":
            return f"{current} {self._TERMINATION_COMPENSATION_TERMS}"
        if loan_intent:
            memory = state.get("legal_memory") or {}
            if hasattr(memory, "model_dump"):
                memory = memory.model_dump(mode="json")
            case = dict((memory or {}).get("current_case") or {})
            fact_keys = (
                "loan_amount_text", "loan_due_date_text", "debt_acknowledgment_channel",
                "debt_acknowledgment_date_text", "repayment_promise_text",
                "repayment_promise_deadline_text",
            )
            facts = " ".join(f"{key}={case[key]}" for key in fact_keys if case.get(key))
            return f"{current} {facts} {self._LIMITATION_PERIOD_TERMS}".strip()
        if lease_intent:
            memory = state.get("legal_memory") or {}
            if hasattr(memory, "model_dump"):
                memory = memory.model_dump(mode="json")
            case = dict((memory or {}).get("current_case") or {})
            fact_keys = (
                "lease_user_role", "rental_defect", "landlord_repair_status",
                "repair_notice_count", "repair_notice_evidence", "rental_habitability_impact",
                "tenant_seeks_termination", "lease_settlement_question", "landlord_name",
                "repair_notice_dates", "property_damage_cause", "damaged_property",
                "property_repair_cost_yuan", "property_repair_invoice", "property_loss_claim_text",
            )
            facts = " ".join(f"{key}={case[key]}" for key in fact_keys if case.get(key) is not None)
            terms_by_intent = {
                "lease_repair_fact_update": self._LEASE_REPAIR_FACT_UPDATE_TERMS,
                "lease_repair_damage_update": self._LEASE_REPAIR_DAMAGE_TERMS,
                "lease_repair_case_recap": self._LEASE_REPAIR_RECAP_TERMS,
                "lease_repair_notice_timeline": self._LEASE_REPAIR_TIMELINE_TERMS,
                "lease_repair_notice_evidence": self._LEASE_REPAIR_NOTICE_TERMS,
                "lease_repair_termination": self._LEASE_REPAIR_TERMINATION_TERMS,
                "lease_repair_settlement": self._LEASE_REPAIR_SETTLEMENT_TERMS,
                "lease_repair_remedy": self._LEASE_REPAIR_TERMS,
            }
            return f"{current} {facts} {terms_by_intent[lease_intent]}".strip()
        if renovation_intent:
            memory = state.get("legal_memory") or {}
            if hasattr(memory, "model_dump"):
                memory = memory.model_dump(mode="json")
            case = dict((memory or {}).get("current_case") or {})
            fact_keys = (
                "renovation_company_name", "renovation_contract_total_yuan", "renovation_paid_yuan",
                "renovation_contract_sign_date", "renovation_completion_due_date",
                "renovation_progress_date", "renovation_progress_percent", "renovation_demand_date",
                "renovation_demand_methods", "renovation_promised_completion_date",
                "renovation_still_incomplete_as_of", "temporary_rent_loss_yuan",
                "renovation_quality_defect", "renovation_downstairs_damage",
                "renovation_repair_estimate_yuan", "renovation_third_party_report",
                "renovation_force_majeure_defense",
            )
            facts = " ".join(f"{key}={case[key]}" for key in fact_keys if case.get(key) is not None)
            return f"{current} {facts} {self._RENOVATION_CONTRACT_TERMS}".strip()
        if any(marker in normalized for marker in ("起诉状", "答辩状", "上诉状", "反诉状")):
            return f"{normalized} {self._PLEADING_TEMPLATE_TERMS}"
        if any(marker in normalized for marker in ("合同模板", "协议模板", "起草合同", "给我一份合同")):
            return f"{query} {self._DOCUMENT_TEMPLATE_TERMS}"
        if ("起诉" in normalized or "立案" in normalized) and any(
            marker in normalized
            for marker in ("材料", "准备", "需要什么", "怎么办理", "办理渠道", "怎么提交")
        ):
            return f"{query} {self._CIVIL_FILING_TERMS}"
        limitation_markers = (
            "诉讼时效", "时效", "最晚多久", "多久必须起诉", "什么时候起诉",
            "过期还能起诉", "一直不还", "欠钱不还", "借钱不还", "催款",
        )
        if any(marker in normalized for marker in limitation_markers):
            return f"{query} {self._LIMITATION_PERIOD_TERMS}"
        wage_arrears_detected = (
            "欠薪" in normalized
            or "拖欠工资" in normalized
            or (
                "工资" in normalized
                and any(marker in normalized for marker in ("拖欠", "没发", "未发", "不发", "克扣", "少发", "不给", "没给"))
            )
        )
        if wage_arrears_detected:
            return f"{query} {self._WAGE_ARREARS_REMEDY_TERMS}"
        traffic_markers = (
            "闯红灯", "撞人", "交通事故", "交通肇事", "车祸", "机动车",
            "酒驾", "醉驾", "肇事逃逸", "驾驶证", "交强险",
        )
        if any(marker in normalized for marker in traffic_markers):
            return f"{query} {self._TRAFFIC_SCENARIO_TERMS}"
        defense_markers = (
            "正当防卫", "防卫过当", "互殴", "还手", "先动手", "打架",
            "反击", "自卫", "制止侵害",
        )
        if any(marker in normalized for marker in defense_markers):
            return f"{query} {self._SELF_DEFENSE_BOUNDARY_TERMS}"
        return query

    async def retrieve_node(self, state):
        """劳动仲裁时效首次空召回时，以法名+条号进行一次精确补检。"""
        result = await super().retrieve_node(state)
        if self._labor_intent(state) == "labor_arbitration_limitation" and not result.get("retrieved_chunks"):
            fallback_state = dict(state)
            fallback_state["targeted_labor_fallback"] = True
            return await super().retrieve_node(fallback_state)
        return result

    def _build_reason_messages(self, state):
        # Supervisor 的 input 可用于编排，但不能替代本轮用户原话成为回答目标。
        # 例如用户只补充离职月份时，禁止按扩写任务泛答社保转移、全部劳动权益。
        reason_state = dict(state)
        reason_state["query"] = self._current_user_query(state)
        messages = super()._build_reason_messages(reason_state)
        labor_intent = self._labor_intent(state)
        prompt_by_intent = {
            "wage_arrears_remedy": "labor_wage_arrears_system",
            "wage_arrears_amount": "labor_wage_arrears_amount_system",
            "wage_arrears_recovery": "labor_wage_arrears_recovery_system",
            "labor_arbitration_limitation": "labor_arbitration_limitation_system",
            "termination_compensation": "labor_termination_compensation_system",
        }
        prompt_key = prompt_by_intent.get(labor_intent)
        traffic_intent = self._traffic_intent(state)
        if traffic_intent == "traffic_medical_expense":
            prompt_key = "traffic_medical_expense_system"
        loan_intent = self._loan_limitation_intent(state)
        if loan_intent:
            prompt_key = "loan_limitation_followup_system"
        lease_intent = self._lease_repair_intent(state)
        renovation_intent = self._renovation_contract_intent(state)
        lease_prompt_by_intent = {
            "lease_repair_remedy": "lease_repair_followup_system",
            "lease_repair_fact_update": "lease_repair_fact_update_system",
            "lease_repair_damage_update": "lease_repair_damage_update_system",
            "lease_repair_case_recap": "lease_repair_case_recap_system",
            "lease_repair_notice_timeline": "lease_repair_notice_timeline_system",
            "lease_repair_notice_evidence": "lease_repair_notice_evidence_system",
            "lease_repair_termination": "lease_repair_termination_system",
            "lease_repair_settlement": "lease_repair_settlement_system",
        }
        if lease_intent:
            prompt_key = lease_prompt_by_intent[lease_intent]
        if renovation_intent:
            prompt_key = "renovation_contract_followup_system"
        if prompt_key:
            messages[0]["content"] += "\n\n" + get_prompt(prompt_key)
            messages[1]["content"] += (
                f"\n\n【本轮专项子意图】{labor_intent or traffic_intent or loan_intent or lease_intent or renovation_intent}"
                f"\n【本轮用户原始问题】{self._current_user_query(state)}"
                f"\n【当前日期】{date.today().isoformat()}"
                "\n必须承接用户历史中已经明确的事实，不重复追问，也不得改写为其他争议。"
            )
        return messages

    def system_prompt(self) -> str:
        """返回普通法律咨询的回答约束。"""
        return get_prompt("law_qa_system")

