# Crpyto_High_Risk_Strategy

高風險加密貨幣策略專案（Copilot + Codex 合併版）

## 專案簡介
- 目標：將 500 USDT 以高風險策略進行槓桿交易，專注於小幣種動能、突破延續、失敗反轉放空。
- 特色：
  - 嚴格 R1-R8 風控規則
  - 多 setup 策略引擎（A/B/C/D）
  - 完整模組化架構
  - 預設 paper trading 與 testnet，安全可測

## 主要模組
- `core/`：scanner, signals, strategy, risk_manager, executor, paper_trader
- `scripts/`：run_scanner.py, run_paper.py
- `utils/`：logger, helpers
- `config/`：settings, pairs_whitelist

## 快速開始
1. 安裝依賴：`pip install -r requirements.txt`
2. 執行模擬交易：`python -m scripts.run_paper`
3. 執行全流程：`python -m scripts.run_scanner --once`

## 風控規則（R1-R8）
- 單日最大虧損、槓桿限制、連續停損冷卻等，詳見 `skill.md`

## 重要說明
- 預設僅允許模擬/測試環境，請確認 API 金鑰與權限
- 詳細設計與合併紀錄見 `skill.md`、`handover/CHANGELOG.md`

---

> 本專案由 Copilot AI Agent 合併與重構，請參考 `task_v1.md` 了解原始精神。
