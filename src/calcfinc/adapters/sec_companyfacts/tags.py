"""Ordered candidate XBRL concepts per calcfinc metric, for US-GAAP filers and for IFRS filers of
20-F and 40-F (concepts of the `ifrs-full` taxonomy come after the US ones).

For each metric and each period, the first concept in the list that the filing reports for that
exact period wins; a lower-priority concept is flagged as an alternate in the fact's mapping
reason. Filers change concepts over time (revenue after ASC 606, for example), so the choice is
made per period, never once for the whole history.

Debt lines are deliberately conservative: only the first available line is used, never a sum of
several, because overlapping concepts (total debt versus its current portion) would double count.
The same holds for IFRS: lease liabilities are not debt here, and "trade and other" receivables and
payables are not read as trade receivables and payables.
"""
from __future__ import annotations

US = "us-gaap"
IFRS = "ifrs-full"
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
    # insurers (checked on five US insurers' filings). No concept is the total underwriting expense
    # (acquisition cost amortization and other underwriting expense are tagged apart), so it is derived
    # from INSURER_TOTAL_COSTS less claims, in parse.py.
    "insurance.net_earned_premium": ((US, "PremiumsEarnedNet"), (US, "PremiumsEarnedNetPropertyAndCasualty")),
    "insurance.claims_incurred": ((US, "PolicyholderBenefitsAndClaimsIncurredNet"),
                                  (US, "IncurredClaimsPropertyCasualtyAndLiability")),
    "insurance.net_investment_income": ((US, "NetInvestmentIncome"),),
}

# Checked on the 20-F and 40-F filings of Infosys, Novo Nordisk, SAP, Shell and Royal Bank of Canada.
# Not mapped: equity-method income (IFRS puts the share of associates inside pre-tax profit), trade
# and other receivables or payables (not trade only), the combined purchase of PP&E and intangibles
# some filers tag, and shares issued (they include treasury shares).
_IFRS_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "revenue": ((IFRS, "Revenue"), (IFRS, "RevenueFromContractsWithCustomers")),
    "cost_of_revenue": ((IFRS, "CostOfSales"),),
    "gross_profit": ((IFRS, "GrossProfit"),),
    "depreciation": ((IFRS, "DepreciationAndAmortisationExpense"),
                     (IFRS, "AdjustmentsForDepreciationAndAmortisationExpense")),
    # InterestExpense is the fallback, as it is for US filers (whose only concept it is)
    "finance_costs": ((IFRS, "FinanceCosts"), (IFRS, "InterestExpense")),
    "pbt": ((IFRS, "ProfitLossBeforeTax"),),
    "tax_expense": ((IFRS, "IncomeTaxExpenseContinuingOperations"),),
    # CurrentTaxExpenseIncome is the current year's charge only; the total is the one that adds the
    # prior-period adjustments (Novo Nordisk tags the two apart and so has no clean total).
    "current_tax": ((IFRS, "CurrentTaxExpenseIncomeAndAdjustmentsForCurrentTaxOfPriorPeriods"),),
    "deferred_tax": ((IFRS, "DeferredTaxExpenseIncome"),),
    "profit_continuing_ops": ((IFRS, "ProfitLossFromContinuingOperations"),),
    "net_profit": ((IFRS, "ProfitLoss"),),
    "net_profit_owners": ((IFRS, "ProfitLossAttributableToOwnersOfParent"),),
    "net_profit_nci": ((IFRS, "ProfitLossAttributableToNoncontrollingInterests"),),
    "oci": ((IFRS, "OtherComprehensiveIncome"),),
    "total_comprehensive_income": ((IFRS, "ComprehensiveIncome"),),
    # Not the continuing-operations EPS: it is not EPS when a filer has discontinued operations, and would be
    # labelled exact. A filer without total EPS gets it derived from profit over shares, with a note.
    "eps_basic": ((IFRS, "BasicEarningsLossPerShare"),),
    "eps_diluted": ((IFRS, "DilutedEarningsLossPerShare"),),
    "total_assets": ((IFRS, "Assets"),),
    "total_liabilities": ((IFRS, "Liabilities"),),
    "total_equity": ((IFRS, "Equity"),),                          # includes minorities, like the US choice
    "current_assets": ((IFRS, "CurrentAssets"),),
    "noncurrent_assets": ((IFRS, "NoncurrentAssets"),),
    "current_liabilities": ((IFRS, "CurrentLiabilities"),),
    "noncurrent_liabilities": ((IFRS, "NoncurrentLiabilities"),),
    "borrowings_current": ((IFRS, "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"),
                           (IFRS, "CurrentPortionOfLongtermBorrowings"), (IFRS, "ShorttermBorrowings")),
    "borrowings_noncurrent": ((IFRS, "LongtermBorrowings"),),
    "cash_and_equivalents": ((IFRS, "CashAndCashEquivalents"),),
    "inventory": ((IFRS, "Inventories"),),
    "trade_receivables": ((IFRS, "CurrentTradeReceivables"),),
    "trade_payables": ((IFRS, "TradeAndOtherCurrentPayablesToTradeSuppliers"),),
    "minority_interest": ((IFRS, "NoncontrollingInterests"),),
    "shares_outstanding": ((IFRS, "NumberOfSharesOutstanding"),),
    "operating_cash_flow": ((IFRS, "CashFlowsFromUsedInOperatingActivities"),),
    "investing_cash_flow": ((IFRS, "CashFlowsFromUsedInInvestingActivities"),),
    "financing_cash_flow": ((IFRS, "CashFlowsFromUsedInFinancingActivities"),),
    "dividends": ((IFRS, "DividendsPaidClassifiedAsFinancingActivities"),
                  (IFRS, "DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities")),
    "capex_ppe": ((IFRS, "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),),
    "capex_intangibles": ((IFRS, "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"),),
}
for _metric, _extra in _IFRS_CANDIDATES.items():
    CANDIDATES[_metric] = (*CANDIDATES.get(_metric, ()), *_extra)

# A filer that files like an IFRS bank. Its interest expense is an operating cost, not a finance
# cost, and bank.* lines are not mapped for IFRS.
IFRS_BANK_MARKERS = frozenset({"DepositsFromBanks", "DepositsFromCustomers"})

# An insurer's total benefits, losses and expenses. Not a metric of its own: the SEC adapter takes claims
# incurred from it to leave insurance.underwriting_expenses (which therefore also holds interest expense,
# interest credited to policyholders, policyholder dividends and whatever else sits inside the total).
INSURER_TOTAL_COSTS: tuple[tuple[str, str], ...] = ((US, "BenefitsLossesAndExpenses"),)

# A US filer that reports premiums earned is an insurer, unless it files like a bank (a large bank
# with an insurance arm tags them too). Without this, NetInvestmentIncome of a fund or a bank would
# be read as an insurer's.
INSURER_MARKERS = frozenset({"PremiumsEarnedNet", "PremiumsEarnedNetPropertyAndCasualty"})

# Filings that contain full financial statements. 8-K, S-1 and the like are ignored. A 6-K carries
# the quarterly statements of the foreign filers that report them (Shell, Royal Bank of Canada).
DEFAULT_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A",
                           "6-K", "6-K/A"})

# The forms that hold a full year's audited statements; the fiscal year end is read from their years.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
