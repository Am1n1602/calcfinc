"""Ordered candidate XBRL concepts per calcfinc metric, for US-GAAP filers.

For each metric and each period, the first concept in the list that the filing reports for that
exact period wins; a lower-priority concept is flagged as an alternate in the fact's mapping
reason. Filers change concepts over time (revenue after ASC 606, for example), so the choice is
made per period, never once for the whole history.

Debt lines are deliberately conservative: only the first available line is used, never a sum of
several, because overlapping concepts (total debt versus its current portion) would double count.
"""
from __future__ import annotations

US = "us-gaap"
DEI = "dei"

CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    # income statement
    # RevenuesNetOfInterestExpense is the total net revenue US banks report each quarter
    "revenue": ((US, "Revenues"), (US, "RevenuesNetOfInterestExpense"),
                (US, "RevenueFromContractWithCustomerExcludingAssessedTax"),
                (US, "RevenueFromContractWithCustomerIncludingAssessedTax"), (US, "SalesRevenueNet"),
                (US, "SalesRevenueGoodsNet")),
    "cost_of_revenue": ((US, "CostOfRevenue"), (US, "CostOfGoodsAndServicesSold"), (US, "CostOfGoodsSold"),
                        (US, "CostOfServices")),
    "gross_profit": ((US, "GrossProfit"),),
    "depreciation": ((US, "DepreciationDepletionAndAmortization"), (US, "DepreciationAndAmortization"),
                     (US, "DepreciationAmortizationAndAccretionNet"), (US, "Depreciation")),
    "finance_costs": ((US, "InterestExpense"), (US, "InterestExpenseDebt"), (US, "InterestAndDebtExpense"),
                      (US, "InterestExpenseNonoperating")),
    "pbt": ((US, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
            (US, "IncomeLossFromContinuingOperationsBeforeIncomeTaxes"
                 "MinorityInterestAndIncomeLossFromEquityMethodInvestments")),
    "tax_expense": ((US, "IncomeTaxExpenseBenefit"),),
    "current_tax": ((US, "CurrentIncomeTaxExpenseBenefit"),),
    "deferred_tax": ((US, "DeferredIncomeTaxExpenseBenefit"),),
    "profit_continuing_ops": ((US, "IncomeLossFromContinuingOperations"),),
    "net_profit": ((US, "ProfitLoss"), (US, "NetIncomeLoss")),            # profit including minorities first
    "net_profit_owners": ((US, "NetIncomeLoss"),),
    "net_profit_nci": ((US, "NetIncomeLossAttributableToNoncontrollingInterest"),),
    # Only the total: the parent-only portion would mix bases with a net profit that includes
    # minorities (a filer with minority holders then fails net profit + OCI = comprehensive income).
    "oci": ((US, "OtherComprehensiveIncomeLossNetOfTax"),),
    "equity_method_income": ((US, "IncomeLossFromEquityMethodInvestments"),),
    "total_comprehensive_income": (
        (US, "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest"),
        (US, "ComprehensiveIncomeNetOfTax")),
    "eps_basic": ((US, "EarningsPerShareBasic"),),
    "eps_diluted": ((US, "EarningsPerShareDiluted"),),
    # balance sheet
    "total_assets": ((US, "Assets"),),
    "total_liabilities": ((US, "Liabilities"),),
    "total_equity": ((US, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
                     (US, "StockholdersEquity")),
    "current_assets": ((US, "AssetsCurrent"),),
    "noncurrent_assets": ((US, "AssetsNoncurrent"),),
    "current_liabilities": ((US, "LiabilitiesCurrent"),),
    "noncurrent_liabilities": ((US, "LiabilitiesNoncurrent"),),
    "borrowings_current": ((US, "DebtCurrent"), (US, "LongTermDebtCurrent"), (US, "ShortTermBorrowings")),
    "borrowings_noncurrent": ((US, "LongTermDebtNoncurrent"),),
    "cash_and_equivalents": ((US, "CashAndCashEquivalentsAtCarryingValue"),
                             (US, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")),
    "inventory": ((US, "InventoryNet"),),
    "trade_receivables": ((US, "AccountsReceivableNetCurrent"),),
    "trade_payables": ((US, "AccountsPayableCurrent"),),
    "minority_interest": ((US, "MinorityInterest"),),
    "preferred_equity": ((US, "PreferredStockValue"),),
    "shares_outstanding": ((US, "CommonStockSharesOutstanding"), (DEI, "EntityCommonStockSharesOutstanding")),
    # cash flow (outflows are reported as positive payments; the ratios take their magnitude)
    "operating_cash_flow": ((US, "NetCashProvidedByUsedInOperatingActivities"),
                            (US, "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
    "investing_cash_flow": ((US, "NetCashProvidedByUsedInInvestingActivities"),
                            (US, "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations")),
    "financing_cash_flow": ((US, "NetCashProvidedByUsedInFinancingActivities"),
                            (US, "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations")),
    "dividends": ((US, "PaymentsOfDividends"), (US, "PaymentsOfDividendsCommonStock")),
    "capex_ppe": ((US, "PaymentsToAcquirePropertyPlantAndEquipment"), (US, "PaymentsToAcquireProductiveAssets")),
    "capex_intangibles": ((US, "PaymentsToAcquireIntangibleAssets"),),
    # banks. Only concepts whose meaning matches the bank.* metric are mapped, checked on a large
    # US bank's filings (interest income less expense equals reported net interest income). Not
    # mapped: non-performing assets (US "nonaccrual" is a different definition), CASA and earning
    # assets (not tagged), and "loans net of allowance" (one filer's value exceeds its gross loans).
    "bank.interest_earned": ((US, "InterestAndDividendIncomeOperating"), (US, "InterestIncomeOperating")),
    "bank.interest_expended": ((US, "InterestExpense"), (US, "InterestExpenseOperating")),
    "bank.provisions": ((US, "ProvisionForLoanLeaseAndOtherLosses"), (US, "ProvisionForLoanAndLeaseLosses")),
    "bank.employee_cost": ((US, "LaborAndRelatedExpense"),),
    "bank.deposits": ((US, "Deposits"),),
    "bank.advances": ((US, "LoansAndLeasesReceivableNetReportedAmount"),),
    "bank.gross_advances": ((US, "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss"),
                            (US, "LoansAndLeasesReceivableNetOfDeferredIncome")),
}

# Filings that contain full financial statements. 8-K, S-1 and the like are ignored.
DEFAULT_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"})
