-- ============================================================================
-- LawAgent 数据库初始化脚本
-- 数据库: MySQL 8.0+
-- 引擎: InnoDB
-- 字符集: utf8mb4
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `lawrag`
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE `lawrag`;

-- ============================================================================
-- 清理已有表（按依赖逆序删除）
-- ============================================================================

DROP TABLE IF EXISTS `contract_risk`;
DROP TABLE IF EXISTS `task_log`;
DROP TABLE IF EXISTS `audit_log`;
DROP TABLE IF EXISTS `rag_trace`;
DROP TABLE IF EXISTS `prompt_template`;
DROP TABLE IF EXISTS `model_config`;
DROP TABLE IF EXISTS `legal_memory`;
DROP TABLE IF EXISTS `message`;
DROP TABLE IF EXISTS `conversation`;
DROP TABLE IF EXISTS `knowledge_chunk`;
DROP TABLE IF EXISTS `knowledge_document`;
DROP TABLE IF EXISTS `knowledge_base`;
DROP TABLE IF EXISTS `user_llm_config`;
DROP TABLE IF EXISTS `evaluation_result`;
DROP TABLE IF EXISTS `llm_usage`;
DROP TABLE IF EXISTS `agent_run_trace`;
DROP TABLE IF EXISTS `question_trace`;
DROP TABLE IF EXISTS `chat_upload`;
DROP TABLE IF EXISTS `user`;

-- ============================================================================
-- 1. user — 用户表
-- ============================================================================

CREATE TABLE `user` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '用户ID',
    `username`        VARCHAR(50)   NOT NULL                 COMMENT '用户名',
    `email`           VARCHAR(100)  NOT NULL                 COMMENT '邮箱',
    `phone`           VARCHAR(20)   DEFAULT NULL             COMMENT '手机号',
    `password_hash`   VARCHAR(255)  NOT NULL                 COMMENT '密码哈希(bcrypt)',
    `avatar`          VARCHAR(500)  DEFAULT NULL             COMMENT '头像OSS地址',
    `role`            VARCHAR(20)   NOT NULL DEFAULT 'user'  COMMENT '角色: admin / user',
    `status`          VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态: active / disabled',
    `last_login_at`   DATETIME      DEFAULT NULL             COMMENT '最后登录时间',
    `created_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`),
    UNIQUE KEY `uk_email`    (`email`),
    KEY `idx_status`         (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- ============================================================================
-- 2. knowledge_base — 知识库表
-- ============================================================================

CREATE TABLE `knowledge_base` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '知识库ID',
    `user_id`         BIGINT        NOT NULL                 COMMENT '所属用户ID',
    `name`            VARCHAR(100)  NOT NULL                 COMMENT '知识库名称',
    `description`     TEXT          DEFAULT NULL             COMMENT '描述',
    `kb_type`         VARCHAR(30)   NOT NULL                 COMMENT '类型: law / case / judicial / contract / enterprise',
    `embedding_model` VARCHAR(100)  DEFAULT 'bge-large-zh-v1.5' COMMENT '绑定的Embedding模型',
    `rerank_model`    VARCHAR(100)  DEFAULT NULL             COMMENT '绑定的Rerank模型',
    `chunk_size`      INT           NOT NULL DEFAULT 500     COMMENT 'Chunk大小(tokens)',
    `chunk_overlap`   INT           NOT NULL DEFAULT 50      COMMENT 'Chunk重叠(tokens)',
    `doc_count`       INT           NOT NULL DEFAULT 0       COMMENT '文档数量(冗余计数)',
    `chunk_count`     INT           NOT NULL DEFAULT 0       COMMENT 'Chunk数量(冗余计数)',
    `total_size`      BIGINT        NOT NULL DEFAULT 0       COMMENT '总文件大小(字节)',
    `status`          VARCHAR(20)   NOT NULL DEFAULT 'enabled' COMMENT '状态: enabled / disabled',
    `created_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_id`  (`user_id`),
    KEY `idx_kb_type`  (`kb_type`),
    KEY `idx_status`   (`status`),
    CONSTRAINT `fk_kb_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';

-- ============================================================================
-- 3. knowledge_document — 知识库文档表
-- ============================================================================

CREATE TABLE `knowledge_document` (
    `id`                        BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '文档ID',
    `kb_id`                     BIGINT        NOT NULL                 COMMENT '所属知识库ID',
    `user_id`                   BIGINT        NOT NULL                 COMMENT '上传用户ID',
    `filename`                  VARCHAR(255)  NOT NULL                 COMMENT '原始文件名',
    `file_type`                 VARCHAR(20)   NOT NULL                 COMMENT '文件类型: pdf / docx / xlsx / txt / image / html',
    `file_size`                 BIGINT        NOT NULL DEFAULT 0       COMMENT '文件大小(字节)',
    `file_hash`                 VARCHAR(64)   NOT NULL                 COMMENT 'SHA256摘要，用于去重',
    `oss_bucket`                VARCHAR(100)  NOT NULL                 COMMENT 'OSS Bucket名称',
    `oss_key`                   VARCHAR(500)  NOT NULL                 COMMENT 'OSS对象Key（存储路径）',
    `oss_url`                   VARCHAR(500)  NOT NULL                 COMMENT 'OSS访问URL',
    `raw_markdown`              MEDIUMTEXT    DEFAULT NULL             COMMENT '解析后的Markdown原文',
    `parse_status`              VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT '解析状态: pending / parsing / completed / failed',
    `embedding_status`          VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT '向量化状态: pending / processing / completed / partial_failed / failed',
    `embedding_count`           INT           NOT NULL DEFAULT 0       COMMENT 'Embedding成功数量',
    `embedding_failed_count`    INT           NOT NULL DEFAULT 0       COMMENT 'Embedding失败数量',
    `error_message`             TEXT          DEFAULT NULL             COMMENT '失败原因',
    `chunk_count`               INT           NOT NULL DEFAULT 0       COMMENT 'Chunk数量',
    `version`                   VARCHAR(20)   DEFAULT NULL             COMMENT '版本号(如2020/2025)',
    `effective_date`            INT           DEFAULT NULL             COMMENT '生效日期Unix时间戳',
    `is_latest`                 TINYINT(1)    NOT NULL DEFAULT 1       COMMENT '是否最新有效版本',
    `superseded_by_document_id` BIGINT        DEFAULT NULL             COMMENT '被哪个文档替代',
    `created_at`                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    `updated_at`                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_oss_key`             (`oss_key`),
    KEY `idx_kb_id`                     (`kb_id`),
    KEY `idx_user_id`                   (`user_id`),
    KEY `idx_parse_status`              (`parse_status`),
    KEY `idx_embedding_status`          (`embedding_status`),
    KEY `idx_file_hash`                 (`file_hash`),
    KEY `idx_version`                   (`version`),
    KEY `idx_is_latest`                 (`is_latest`),
    KEY `idx_superseded_by_document_id` (`superseded_by_document_id`),
    CONSTRAINT `fk_doc_kb`   FOREIGN KEY (`kb_id`)   REFERENCES `knowledge_base` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_doc_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文档表';

-- ============================================================================
-- 4. knowledge_chunk — 知识库Chunk表
-- ============================================================================

CREATE TABLE `knowledge_chunk` (
    `id`               BIGINT        NOT NULL AUTO_INCREMENT  COMMENT 'Chunk ID',
    `document_id`      BIGINT        NOT NULL                 COMMENT '所属文档ID',
    `kb_id`            BIGINT        NOT NULL                 COMMENT '所属知识库ID',
    `chunk_index`      INT           NOT NULL                 COMMENT 'Chunk序号(从0开始)',
    `parent_chunk_id`  VARCHAR(128)  DEFAULT NULL             COMMENT '父级Chunk ID(Section→Chapter→Book)',
    `chunk_type`       VARCHAR(30)   NOT NULL DEFAULT 'law'   COMMENT '大类: law / judicial / case / contract / enterprise',
    `chunk_level`      VARCHAR(32)   DEFAULT NULL             COMMENT '层级: book / chapter / section / article / paragraph / clause',
    `chunk_subtype`    VARCHAR(64)   DEFAULT NULL             COMMENT '子类型: article / case_basic_info / court_view / judgment_result / liability / payment / termination / policy_rule',
    `text`             MEDIUMTEXT    NOT NULL                 COMMENT 'Chunk原文',
    `token_count`      INT           NOT NULL DEFAULT 0       COMMENT 'Token数量',
    `vector_id`        VARCHAR(100)  DEFAULT NULL             COMMENT 'Milvus向量ID',
    `metadata`         JSON          DEFAULT NULL             COMMENT '扩展元数据(法条信息、案由、关键词等)',
    `created_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_doc_chunk`      (`document_id`, `chunk_index`),
    KEY `idx_document_id`     (`document_id`),
    KEY `idx_kb_id`           (`kb_id`),
    KEY `idx_vector_id`       (`vector_id`),
    KEY `idx_parent_chunk_id` (`parent_chunk_id`),
    CONSTRAINT `fk_chunk_doc` FOREIGN KEY (`document_id`) REFERENCES `knowledge_document` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_chunk_kb`  FOREIGN KEY (`kb_id`)       REFERENCES `knowledge_base` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库Chunk表';

-- ============================================================================
-- 5. conversation — 会话表
-- ============================================================================

CREATE TABLE `conversation` (
    `id`             BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '会话ID',
    `user_id`        BIGINT        NOT NULL                 COMMENT '用户ID',
    `kb_id`          BIGINT        DEFAULT NULL             COMMENT '关联的知识库ID(可选)',
    `title`          VARCHAR(200)  NOT NULL DEFAULT '新的对话' COMMENT '会话标题',
    `agent_type`     VARCHAR(30)   NOT NULL DEFAULT 'law_qa' COMMENT 'Agent类型: law_qa / case_analysis / contract_review / article_locate / document_generate',
    `summary`        TEXT          DEFAULT NULL             COMMENT 'AI生成的会话摘要',
    `message_count`  INT           NOT NULL DEFAULT 0       COMMENT '消息数(冗余计数)',
    `total_tokens`   INT           NOT NULL DEFAULT 0       COMMENT '累计Token消耗',
    `status`         VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态: active / archived',
    `created_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_id`        (`user_id`),
    KEY `idx_kb_id`          (`kb_id`),
    KEY `idx_status`         (`status`),
    KEY `idx_updated_at`     (`updated_at`),
    CONSTRAINT `fk_conv_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_conv_kb`   FOREIGN KEY (`kb_id`)   REFERENCES `knowledge_base` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话表';

-- ============================================================================
-- 6. message — 消息表
-- ============================================================================

CREATE TABLE `message` (
    `id`                 BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '消息ID',
    `conversation_id`    BIGINT        NOT NULL                 COMMENT '所属会话ID',
    `user_id`            BIGINT        DEFAULT NULL             COMMENT '用户ID(系统消息为null)',
    `role`               VARCHAR(20)   NOT NULL                 COMMENT '角色: user / assistant / system',
    `content`            MEDIUMTEXT    NOT NULL                 COMMENT '消息正文(Markdown)',
    `citations`          JSON          DEFAULT NULL             COMMENT '引用列表(assistant消息)',
    `feedback`           VARCHAR(20)   DEFAULT NULL             COMMENT '用户反馈: like / dislike',
    `feedback_comment`   TEXT          DEFAULT NULL             COMMENT '反馈备注',
    `token_usage`        INT           NOT NULL DEFAULT 0       COMMENT '本条Token消耗',
    `latency_ms`         INT           NOT NULL DEFAULT 0       COMMENT '响应耗时(毫秒)',
    `retrieval_trace_id` VARCHAR(50)   DEFAULT NULL             COMMENT '关联检索Trace UUID',
    `created_at`         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_conversation_id` (`conversation_id`),
    KEY `idx_user_id`         (`user_id`),
    KEY `idx_created_at`      (`created_at`),
    CONSTRAINT `fk_msg_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversation` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_msg_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息表';

-- ============================================================================
-- 7. legal_memory — 法律上下文记忆表
-- ============================================================================

CREATE TABLE `legal_memory` (
    `id`                 BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '记忆ID',
    `conversation_id`    BIGINT        NOT NULL                 COMMENT '所属会话ID',
    `current_law`        VARCHAR(200)  DEFAULT NULL             COMMENT '当前讨论的法律',
    `current_article`    VARCHAR(50)   DEFAULT NULL             COMMENT '当前讨论的法条',
    `current_topic`      VARCHAR(200)  DEFAULT NULL             COMMENT '当前讨论的主题',
    `mentioned_laws`     JSON          DEFAULT NULL             COMMENT '对话中提及的法律列表',
    `mentioned_articles` JSON          DEFAULT NULL             COMMENT '对话中引用的法条列表',
    `user_facts`         JSON          DEFAULT NULL             COMMENT '用户提供的事实要素',
    `key_points`         JSON          DEFAULT NULL             COMMENT '关键信息摘要',
    `updated_at`         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_conversation_id` (`conversation_id`),
    CONSTRAINT `fk_memory_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversation` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='法律上下文记忆表';

-- ============================================================================
-- 8. model_config — 模型配置表
-- ============================================================================

CREATE TABLE `model_config` (
    `id`                BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '配置ID',
    `provider`          VARCHAR(50)   NOT NULL                 COMMENT '供应商: deepseek / openai / qwen / claude / zhipu',
    `model_name`        VARCHAR(100)  NOT NULL                 COMMENT '模型名: deepseek-v3 / gpt-4o / qwen-max',
    `model_type`        VARCHAR(30)   NOT NULL                 COMMENT '模型类型: chat / embedding / rerank / vlm',
    `api_base`          VARCHAR(300)  DEFAULT NULL             COMMENT '自定义API地址',
    `api_key_encrypted` VARCHAR(500)  DEFAULT NULL             COMMENT '加密的API Key',
    `max_tokens`        INT           NOT NULL DEFAULT 4096    COMMENT '最大输出Token',
    `temperature`       DECIMAL(3,2)  NOT NULL DEFAULT 0.10    COMMENT '默认温度',
    `is_default`        TINYINT(1)    NOT NULL DEFAULT 0       COMMENT '是否默认模型',
    `priority`          INT           NOT NULL DEFAULT 0       COMMENT '优先级(数字越大越优先)',
    `status`            VARCHAR(20)   NOT NULL DEFAULT 'enabled' COMMENT '状态: enabled / disabled',
    `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_provider_model` (`provider`, `model_name`),
    KEY `idx_model_type`           (`model_type`),
    KEY `idx_status`               (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型配置表';

-- ============================================================================
-- 9. rag_trace — RAG检索链路Trace表
-- ============================================================================

CREATE TABLE `rag_trace` (
    `id`                   BIGINT        NOT NULL AUTO_INCREMENT  COMMENT 'Trace ID',
    `trace_id`             VARCHAR(50)   NOT NULL                 COMMENT 'Trace UUID',
    `message_id`           BIGINT        DEFAULT NULL             COMMENT '关联消息ID',
    `conversation_id`      BIGINT        DEFAULT NULL             COMMENT '关联会话ID',
    `user_id`              BIGINT        DEFAULT NULL             COMMENT '用户ID',
    `agent_type`           VARCHAR(30)   DEFAULT NULL             COMMENT 'Agent类型',
    `original_query`       TEXT          NOT NULL                 COMMENT '用户原始问题',
    `rewritten_query`      TEXT          DEFAULT NULL             COMMENT '改写后查询',
    `expanded_queries`     JSON          DEFAULT NULL             COMMENT '扩展查询列表',
    `bm25_results`         JSON          DEFAULT NULL             COMMENT 'BM25检索结果(top20)',
    `milvus_results`       JSON          DEFAULT NULL             COMMENT 'Milvus检索结果(top20)',
    `merged_results`       JSON          DEFAULT NULL             COMMENT '融合后结果',
    `reranked_results`     JSON          DEFAULT NULL             COMMENT '重排后结果(最终注入LLM的Chunk)',
    `final_context`        MEDIUMTEXT    DEFAULT NULL             COMMENT '注入LLM的最终上下文',
    `citation_count`       INT           NOT NULL DEFAULT 0       COMMENT '引用数量',
    `total_latency_ms`     INT           NOT NULL DEFAULT 0       COMMENT '检索总耗时(毫秒)',
    `retrieval_latency_ms` INT           NOT NULL DEFAULT 0       COMMENT '纯检索耗时(毫秒)',
    `created_at`           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_trace_id`   (`trace_id`),
    KEY `idx_message_id`       (`message_id`),
    KEY `idx_user_id`          (`user_id`),
    KEY `idx_agent_type`       (`agent_type`),
    KEY `idx_created_at`       (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RAG检索链路Trace表';

-- ============================================================================
-- 10. audit_log — 操作审计日志表
-- ============================================================================

CREATE TABLE `audit_log` (
    `id`            BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '日志ID',
    `user_id`       BIGINT        DEFAULT NULL             COMMENT '操作用户ID',
    `action`        VARCHAR(50)   NOT NULL                 COMMENT '操作: create / update / delete / login / logout / upload / download',
    `resource_type` VARCHAR(50)   NOT NULL                 COMMENT '资源类型: kb / document / chunk / conversation / user / model / prompt',
    `resource_id`   BIGINT        DEFAULT NULL             COMMENT '资源ID',
    `detail`        JSON          DEFAULT NULL             COMMENT '操作详情',
    `ip_address`    VARCHAR(50)   DEFAULT NULL             COMMENT '客户端IP',
    `user_agent`    VARCHAR(500)  DEFAULT NULL             COMMENT 'User-Agent',
    `created_at`    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
    PRIMARY KEY (`id`),
    KEY `idx_user_id`      (`user_id`),
    KEY `idx_action`       (`action`),
    KEY `idx_resource`     (`resource_type`, `resource_id`),
    KEY `idx_created_at`   (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作审计日志表';

-- ============================================================================
-- 11. task_log — 异步任务日志表
-- ============================================================================

CREATE TABLE `task_log` (
    `id`            BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '任务ID',
    `task_type`     VARCHAR(30)   NOT NULL                 COMMENT '任务类型: document_parse / embedding / contract_review / report_export',
    `resource_type` VARCHAR(50)   DEFAULT NULL             COMMENT '关联资源类型',
    `resource_id`   BIGINT        DEFAULT NULL             COMMENT '关联资源ID',
    `user_id`       BIGINT        DEFAULT NULL             COMMENT '发起用户ID',
    `status`        VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT '状态: pending / running / completed / failed / cancelled',
    `input_params`  JSON          DEFAULT NULL             COMMENT '输入参数',
    `output_result` JSON          DEFAULT NULL             COMMENT '输出结果',
    `error_message` TEXT          DEFAULT NULL             COMMENT '错误信息',
    `retry_count`   INT           NOT NULL DEFAULT 0       COMMENT '重试次数',
    `started_at`    DATETIME      DEFAULT NULL             COMMENT '开始执行时间',
    `finished_at`   DATETIME      DEFAULT NULL             COMMENT '完成时间',
    `created_at`    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_task_type`   (`task_type`),
    KEY `idx_status`      (`status`),
    KEY `idx_user_id`     (`user_id`),
    KEY `idx_created_at`  (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='异步任务日志表';

-- ============================================================================
-- 12. user_llm_config — 用户 LLM 配置表(BYOK)
-- ============================================================================

CREATE TABLE `user_llm_config` (
    `id`                  BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '主键ID',
    `user_id`             BIGINT        NOT NULL                 COMMENT '用户ID',
    `config_type`         VARCHAR(20)   NOT NULL DEFAULT 'chat'  COMMENT '配置类型: chat / embedding / rerank',
    `provider`            VARCHAR(50)   NOT NULL                 COMMENT 'LLM provider: openai / deepseek / qwen',
    `model_name`          VARCHAR(100)  NOT NULL                 COMMENT '模型名',
    `api_base`            VARCHAR(255)  NOT NULL DEFAULT ''     COMMENT 'API base URL，为空走 provider 默认',
    `api_key_encrypted`   VARCHAR(500)  NOT NULL DEFAULT ''     COMMENT 'Fernet 加密后的 API Key',
    `is_active`           TINYINT(1)    NOT NULL DEFAULT 1       COMMENT '是否启用: 0 / 1',
    `temperature`         FLOAT         DEFAULT NULL             COMMENT '温度覆盖',
    `max_tokens`          INT           DEFAULT NULL             COMMENT 'max tokens 覆盖',
    `timeout`             INT           DEFAULT NULL             COMMENT '超时秒覆盖',
    `retry`               INT           DEFAULT NULL             COMMENT '重试次数覆盖',
    `dimension`           INT           DEFAULT NULL             COMMENT 'Embedding 向量维度',
    `created_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_llm_config_type` (`user_id`, `config_type`),
    KEY `idx_user_llm_config_user` (`user_id`),
    CONSTRAINT `fk_user_llm_config_user` FOREIGN KEY (`user_id`) REFERENCES `user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户 LLM 配置表(BYOK)';

-- ============================================================================
-- 13. contract_risk — 合同审查风险表
-- ============================================================================

CREATE TABLE `contract_risk` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT  COMMENT '主键ID',
    `task_id`         BIGINT        NOT NULL                 COMMENT '审查任务ID(task_log.id)',
    `document_id`     BIGINT        NOT NULL                 COMMENT '合同文档ID',
    `clause_id`       BIGINT        DEFAULT NULL             COMMENT '条款chunk ID，NULL=全局风险',
    `article_no`      VARCHAR(50)   DEFAULT NULL             COMMENT '冗余条款编号，便于前端展示',
    `risk_level`      VARCHAR(20)   NOT NULL                 COMMENT '风险等级: high/medium/low',
    `risk_type`       VARCHAR(50)   NOT NULL                 COMMENT '风险类型: payment/jurisdiction/termination...',
    `title`           VARCHAR(200)  NOT NULL                 COMMENT '风险标题',
    `description`     TEXT          NOT NULL                 COMMENT '风险描述',
    `excerpt`         TEXT          DEFAULT NULL             COMMENT '合同原文摘录',
    `suggestion`      TEXT          DEFAULT NULL             COMMENT '修改建议',
    `law_references`  JSON          DEFAULT NULL             COMMENT '法律依据列表，如["民法典第585条"]',
    `source`          VARCHAR(20)   NOT NULL                 COMMENT '风险来源: rule/rag/llm',
    `created_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_contract_risk_task`  (`task_id`),
    KEY `idx_contract_risk_clause` (`clause_id`),
    KEY `idx_contract_risk_level` (`task_id`, `risk_level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='合同审查风险表';

-- ============================================================================
-- 13. agent_run_trace — Agent run 级全链路 Trace 表（doc 21 §5.1）
-- ============================================================================

CREATE TABLE `agent_run_trace` (
    `id`                   BIGINT        NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `trace_id`             VARCHAR(50)   NOT NULL                 COMMENT 'run 级链路ID，关联 rag_trace.trace_id / llm_usage.trace_id / evaluation_result.trace_id',
    `plan_id`              VARCHAR(50)   DEFAULT NULL             COMMENT '计划ID(PlanDAG.plan_id)',
    `conversation_id`      BIGINT        DEFAULT NULL             COMMENT '会话ID(conversation.id)',
    `user_id`              BIGINT        DEFAULT NULL             COMMENT '用户ID(user.id)',
    `query`                TEXT          DEFAULT NULL             COMMENT '改写后 query',
    `intent`               JSON          DEFAULT NULL             COMMENT '意图识别结果',
    `plan`                 JSON          DEFAULT NULL             COMMENT 'Plan DAG 快照',
    `step_traces`          JSON          DEFAULT NULL             COMMENT 'StepTrace[] 序列化',
    `agent_results_summary` JSON         DEFAULT NULL             COMMENT '各 Agent 产出摘要(不含全文)',
    `review`               JSON          DEFAULT NULL             COMMENT 'Reviewer 结论',
    `final_answer`         MEDIUMTEXT    DEFAULT NULL             COMMENT '最终答案',
    `final_citations`      JSON          DEFAULT NULL             COMMENT '最终引用列表',
    `needs_human_review`   TINYINT       NOT NULL DEFAULT 0       COMMENT '是否需要人工复核',
    `total_latency_ms`     INT           NOT NULL DEFAULT 0       COMMENT '本次 run 总耗时(毫秒)',
    `status`               VARCHAR(20)   NOT NULL DEFAULT 'success' COMMENT '状态: success/failed/hitl',
    `error`                TEXT          DEFAULT NULL             COMMENT '错误信息',
    `experiment_variant`   VARCHAR(40)   DEFAULT NULL             COMMENT 'A/B 实验变体，如 synthesizer_ab:B',
    `created_at`           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_agent_run_trace_trace` (`trace_id`),
    KEY `idx_agent_run_trace_conversation` (`conversation_id`),
    KEY `idx_agent_run_trace_user` (`user_id`),
    KEY `idx_agent_run_trace_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent run 级全链路Trace表';

-- ============================================================================
-- 14. llm_usage — LLM 调用用量计费表（doc 21 §5.2）
-- ============================================================================

CREATE TABLE `llm_usage` (
    `id`                BIGINT        NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `trace_id`          VARCHAR(50)   NOT NULL                 COMMENT 'run 级链路ID',
    `message_id`        BIGINT        DEFAULT NULL             COMMENT '消息ID(message.id)，离线 Worker 场景可为空',
    `user_id`           BIGINT        DEFAULT NULL             COMMENT '用户ID(user.id)',
    `provider`          VARCHAR(30)   NOT NULL                 COMMENT 'LLM 提供方: openai/deepseek/qwen',
    `model`             VARCHAR(60)   NOT NULL                 COMMENT '模型名称',
    `prompt_tokens`     INT           NOT NULL DEFAULT 0       COMMENT '输入 token 数',
    `completion_tokens` INT           NOT NULL DEFAULT 0       COMMENT '输出 token 数',
    `total_tokens`      INT           NOT NULL DEFAULT 0       COMMENT '总 token 数',
    `latency_ms`        INT           NOT NULL DEFAULT 0       COMMENT '单次调用耗时(毫秒)',
    `cost`              DECIMAL(10,6) NOT NULL DEFAULT 0       COMMENT '估算成本(元)',
    `purpose`           VARCHAR(30)   NOT NULL DEFAULT 'general' COMMENT '调用用途: router/agent/synthesize/review/general',
    `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_llm_usage_trace` (`trace_id`),
    KEY `idx_llm_usage_user` (`user_id`),
    KEY `idx_llm_usage_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LLM 调用用量计费表';

-- ============================================================================
-- 15. evaluation_result — Agent 产出质量评分表（doc 21 §5.3）
-- ============================================================================

CREATE TABLE `evaluation_result` (
    `id`              BIGINT        NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `trace_id`        VARCHAR(50)   NOT NULL                 COMMENT 'run 级链路ID',
    `mode`            VARCHAR(10)   NOT NULL DEFAULT 'online' COMMENT '评分方式: online(确定性)/offline(LLM评审)',
    `citation_score`  FLOAT         DEFAULT NULL             COMMENT '引用编号完整性得分(0-1)',
    `coverage`        FLOAT         DEFAULT NULL             COMMENT '引用覆盖度得分(0-1)',
    `grounded_score`  FLOAT         DEFAULT NULL             COMMENT '论断落地支撑得分(离线评审)',
    `hallucination`   FLOAT         DEFAULT NULL             COMMENT '幻觉占比(离线评审)',
    `overall`         FLOAT         DEFAULT NULL             COMMENT '加权总分',
    `detail`          JSON          DEFAULT NULL             COMMENT '失败论断/未覆盖法条等明细',
    `created_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    KEY `idx_evaluation_trace` (`trace_id`),
    KEY `idx_evaluation_mode` (`mode`),
    KEY `idx_evaluation_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent 产出质量评分表';

-- ============================================================================
-- 16. question_trace — 提问级 Agent/工具执行链路 Trace 表（doc 21 扩展）
-- ============================================================================

CREATE TABLE `question_trace` (
    `id`                BIGINT        NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `trace_id`          VARCHAR(50)   NOT NULL                 COMMENT 'run 级链路ID，与 llm_usage/evaluation_result 同源',
    `conversation_id`   BIGINT        DEFAULT NULL             COMMENT '会话ID(conversation.id)',
    `user_id`           BIGINT        DEFAULT NULL             COMMENT '用户ID(user.id)',
    `query`             TEXT          DEFAULT NULL             COMMENT '用户原始提问',
    `intent`            VARCHAR(60)   DEFAULT NULL             COMMENT '意图/入口(entry_hint 或单 Agent 决策 agent)',
    `engine`            VARCHAR(20)   DEFAULT NULL             COMMENT '编排引擎: supervisor/pipeline_v2/single_agent',
    `status`            VARCHAR(20)   NOT NULL DEFAULT 'success' COMMENT '状态: success/failed/hitl',
    `agents`            JSON          DEFAULT NULL             COMMENT 'Agent 调用序列(含嵌套 tools)',
    `total_latency_ms`  INT           NOT NULL DEFAULT 0       COMMENT '本次提问总耗时(毫秒)',
    `answer_snippet`    VARCHAR(500)  DEFAULT NULL             COMMENT '最终答案摘要',
    `error`             TEXT          DEFAULT NULL             COMMENT '错误信息',
    `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_question_trace_trace` (`trace_id`),
    KEY `idx_question_trace_user` (`user_id`),
    KEY `idx_question_trace_engine` (`engine`),
    KEY `idx_question_trace_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='提问级 Agent/工具执行链路 Trace 表';

-- ============================================================================
-- 17. chat_upload — 会话临时上传文件表
-- ============================================================================

CREATE TABLE `chat_upload` (
    `id`                BIGINT        NOT NULL AUTO_INCREMENT COMMENT '上传ID',
    `user_id`           BIGINT        NOT NULL                 COMMENT '所属用户ID',
    `conversation_id`   BIGINT        DEFAULT NULL             COMMENT '关联会话ID',
    `filename`          VARCHAR(255)  NOT NULL                 COMMENT '原始文件名',
    `file_type`         VARCHAR(20)   NOT NULL                 COMMENT '文件类型: pdf / docx / txt / html / image',
    `doc_type`          VARCHAR(30)   NOT NULL DEFAULT 'contract' COMMENT '业务文档类型: contract',
    `file_size`         BIGINT        NOT NULL DEFAULT 0       COMMENT '文件大小(字节)',
    `file_hash`         VARCHAR(64)   NOT NULL                 COMMENT 'SHA256摘要',
    `oss_bucket`        VARCHAR(100)  DEFAULT NULL             COMMENT 'OSS Bucket',
    `oss_key`           VARCHAR(500)  DEFAULT NULL             COMMENT 'OSS对象Key',
    `oss_url`           VARCHAR(500)  DEFAULT NULL             COMMENT 'OSS存储地址',
    `parse_status`      VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT '解析状态: pending / parsing / completed / failed',
    `parse_warnings`    JSON          DEFAULT NULL             COMMENT '解析降级提示',
    `raw_markdown`      MEDIUMTEXT    DEFAULT NULL             COMMENT '解析后的Markdown原文',
    `clause_count`      INT           NOT NULL DEFAULT 0       COMMENT '合同条款数量',
    `analysis_status`   VARCHAR(20)   NOT NULL DEFAULT 'pending' COMMENT '分析状态: pending / running / completed / failed',
    `analysis_report`   MEDIUMTEXT    DEFAULT NULL             COMMENT '分析最终报告(markdown)',
    `analysis_summary`  MEDIUMTEXT    DEFAULT NULL             COMMENT '合同摘要',
    `analysis_elements` JSON          DEFAULT NULL             COMMENT '合同要素结构化数据',
    `analysis_risks`    JSON          DEFAULT NULL             COMMENT '风险清单结构化数据',
    `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `expires_at`        DATETIME      NOT NULL                 COMMENT '过期时间(到期自动清理)',
    PRIMARY KEY (`id`),
    KEY `idx_chat_upload_user` (`user_id`),
    KEY `idx_chat_upload_conversation` (`conversation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话临时上传文件表';

-- ============================================================================
-- 初始化数据: 默认模型配置
-- ============================================================================

INSERT INTO `model_config` (`provider`, `model_name`, `model_type`, `is_default`, `priority`, `max_tokens`, `temperature`) VALUES
('deepseek', 'deepseek-v3',   'chat',      1, 10, 4096, 0.10),
('deepseek', 'deepseek-r1',   'chat',      0, 5,  8192, 0.10),
('openai',   'gpt-4o',        'chat',      0, 5,  4096, 0.10),
('qwen',     'qwen-max',      'chat',      0, 5,  4096, 0.10),
('zhipu',    'glm-4',         'chat',      0, 3,  4096, 0.10),
('openai',   'text-embedding-3-large', 'embedding', 1, 10, 0, 0.00),
('bge',      'bge-large-zh-v1.5',     'embedding', 0, 8,  0, 0.00),
('bge',      'bge-reranker-v2-m3',    'rerank',    1, 10, 0, 0.00),
('cohere',   'rerank-v3',             'rerank',    0, 5,  0, 0.00);
