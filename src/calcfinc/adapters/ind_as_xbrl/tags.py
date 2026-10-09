"""Ind-AS XBRL tag map: exchange taxonomy concepts -> canonical names.

Ported from the author's earlier extraction code. The names on the left are the *source-side*
canonical names that code used; `NAME_MAP` renames the few that differ from calcfinc's
vocabulary. Concepts live under the `in-capmkt:` taxonomy; older Regulation 33 filings use
`in-bse-fin:` with the same local names, so `map_facts` falls back to the local name.
"""
from __future__ import annotations

import re

TAG_MAP: dict[str, str] = {
    # P&L
    "revenue": "in-capmkt:RevenueFromOperations",
    "other_income": "in-capmkt:OtherIncome",
    "total_income": "in-capmkt:Income",
    "employee_expense": "in-capmkt:EmployeeBenefitExpense",
    "depreciation": "in-capmkt:DepreciationDepletionAndAmortisationExpense",
    "other_expenses": "in-capmkt:OtherExpenses",
    "finance_costs": "in-capmkt:FinanceCosts",
    "total_expenses": "in-capmkt:Expenses",
    "pbt_before_exceptional": "in-capmkt:ProfitBeforeExceptionalItemsAndTax",
    "exceptional_items": "in-capmkt:ExceptionalItemsBeforeTax",
    "pbt": "in-capmkt:ProfitBeforeTax",
    "current_tax": "in-capmkt:CurrentTax",
    "deferred_tax": "in-capmkt:DeferredTax",
    "tax_expense": "in-capmkt:TaxExpense",
    "pat_continuing_ops": "in-capmkt:ProfitLossForPeriodFromContinuingOperations",
    "net_profit": "in-capmkt:ProfitLossForPeriod",
    "oci": "in-capmkt:OtherComprehensiveIncomeNetOfTaxes",
    "total_comprehensive_income": "in-capmkt:ComprehensiveIncomeForThePeriod",
    "net_profit_owners": "in-capmkt:ProfitOrLossAttributableToOwnersOfParent",
    "net_profit_nci": "in-capmkt:ProfitOrLossAttributableToNonControllingInterests",
    "eps_basic": "in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "eps_diluted": "in-capmkt:DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    # equity / capital and the ratios SEBI makes issuers report
    "paid_up_equity_capital": "in-capmkt:PaidUpValueOfEquityShareCapital",
    "face_value_per_share": "in-capmkt:FaceValueOfEquityShareCapital",
    "debt_equity_ratio_reported": "in-capmkt:DebtEquityRatio",
    "debt_service_coverage_ratio_reported": "in-capmkt:DebtServiceCoverageRatio",
    "interest_service_coverage_ratio_reported": "in-capmkt:InterestServiceCoverageRatio",
    # balance sheet
    "total_assets": "in-capmkt:Assets",
    "total_liabilities": "in-capmkt:Liabilities",
    "total_equity": "in-capmkt:Equity",
    "current_assets": "in-capmkt:CurrentAssets",
    "noncurrent_assets": "in-capmkt:NoncurrentAssets",
    "current_liabilities": "in-capmkt:CurrentLiabilities",
    "noncurrent_liabilities": "in-capmkt:NoncurrentLiabilities",
    "borrowings_current": "in-capmkt:BorrowingsCurrent",
    "borrowings_noncurrent": "in-capmkt:BorrowingsNoncurrent",
    "cash_and_equivalents": "in-capmkt:CashAndCashEquivalents",
    # cash flow
    "operating_cash_flow": "in-capmkt:CashFlowsFromUsedInOperatingActivities",
    "investing_cash_flow": "in-capmkt:CashFlowsFromUsedInInvestingActivities",
    "financing_cash_flow": "in-capmkt:CashFlowsFromUsedInFinancingActivities",
    "dividends": "in-capmkt:DividendsPaidClassifiedAsFinancingActivities",
    "capex_ppe": "in-capmkt:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "capex_intangibles": "in-capmkt:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
    # insurers (life insurers file net premium income; it marks the filer as an insurer)
    "insurance_net_premium": "in-capmkt:NetPremiumIncome",
    # banks
    "bank_interest_earned": "in-capmkt:InterestEarned",
    "bank_interest_expended": "in-capmkt:InterestExpended",
    "bank_operating_profit": "in-capmkt:OperatingProfitBeforeProvisionAndContingencies",
    "bank_provisions": "in-capmkt:ProvisionsOtherThanTaxAndContingencies",
    "bank_employee_cost": "in-capmkt:EmployeesCost",
    "bank_other_operating_expenses": "in-capmkt:OtherOperatingExpenses",
    "advances": "in-capmkt:Advances",
    # Bank capital adequacy and asset quality are reported at the bank entity (standalone)
    # level only; consolidated filings carry zeros.
    "cet1_ratio": "in-capmkt:CET1Ratio",
    "additional_tier1_ratio": "in-capmkt:AdditionalTier1Ratio",
    "gross_npa": "in-capmkt:GrossNonPerformingAssets",
    # `NonPerformingAssets` is the NET figure (confirmed against a bank's own NPA ratios).
    "net_npa": "in-capmkt:NonPerformingAssets",
    "gross_npa_ratio": "in-capmkt:PercentageOfGrossNpa",
    "net_npa_ratio": "in-capmkt:PercentageOfNpa",
    # Filers tag this with a currency unit although it is a plain ratio; the unit is taken
    # from the metric registry, not from the raw tag, so the mistake is harmless.
    "return_on_assets": "in-capmkt:ReturnOnAssets",
}

BANK_EQUITY_AUX_TAGS = {
    "_bank_capital": "in-capmkt:Capital",
    "_bank_reserves_and_surplus": "in-capmkt:ReservesAndSurplus",
}
BANK_BALANCE_SHEET_AUX_TAGS = {
    "_bank_cash_with_rbi": "in-capmkt:CashAndBalancesWithReserveBankOfIndia",
    "_bank_balances_with_banks": "in-capmkt:BalancesWithBanksAndMoneyAtCallAndShortNotice",
    "_bank_other_liabilities_and_provisions": "in-capmkt:OtherLiabilitiesAndProvisions",
}
SECTOR_ALT_TAGS = {
    "in-capmkt:ShareholdersFunds": "total_equity",
    "in-capmkt:ProfitLossForThePeriod": "net_profit",
    "in-capmkt:ProfitLossAfterTaxAndExtraordinaryItems": "net_profit",
    "in-capmkt:ProfitLossFromOrdinaryActivitiesBeforeTax": "pbt",
}
DEBT_ALT_TAGS = {
    "in-capmkt:Borrowings": "borrowings_noncurrent",
    "in-capmkt:LongTermBorrowings": "borrowings_noncurrent",
    "in-capmkt:ShortTermBorrowings": "borrowings_current",
    "in-capmkt:DebtSecurities": "debt_securities",
    "in-capmkt:Deposits": "deposits_debt",
}

# Source-side canonical name -> calcfinc metric name (names not listed are unchanged).
NAME_MAP = {
    "pat_continuing_ops": "profit_continuing_ops",
    "insurance_net_premium": "insurance.net_earned_premium",
    "bank_interest_earned": "bank.interest_earned",
    "bank_interest_expended": "bank.interest_expended",
    "bank_operating_profit": "bank.operating_profit",
    "bank_provisions": "bank.provisions",
    "bank_employee_cost": "bank.employee_cost",
    "bank_other_operating_expenses": "bank.other_operating_expenses",
    "advances": "bank.advances",
    "cet1_ratio": "bank.cet1_ratio",
    "additional_tier1_ratio": "bank.additional_tier1_ratio",
    "gross_npa": "bank.gross_npa",
    "net_npa": "bank.net_npa",
    "gross_npa_ratio": "bank.gross_npa_ratio",
    "net_npa_ratio": "bank.net_npa_ratio",
    "return_on_assets": "india.return_on_assets_reported",
}

# The primary whole-company contexts: OneD / OneI, TwoD ..., and PY_D / PY_I for the prior
# year. Segment and note-breakdown contexts (OneReportable1D, OneExpenses2D...) are rejected.
PRIMARY_CONTEXT = re.compile(r"^(One|Two|Three|Four|Five|Six)[DI]$|^PY_[DI]$")

# Fields compared across contexts that share a date, to catch a filing that disagrees with itself.
SNAPSHOT_FIELDS = (
    "total_assets", "total_liabilities", "total_equity", "current_assets", "noncurrent_assets",
    "current_liabilities", "noncurrent_liabilities", "borrowings_current", "borrowings_noncurrent",
    "debt_securities", "deposits_debt", "cash_and_equivalents", "paid_up_equity_capital",
    "face_value_per_share",
)
HIGH_SEVERITY = frozenset({"paid_up_equity_capital", "face_value_per_share", "total_assets", "total_equity"})

META_KEYS = frozenset({"context_id", "period_start", "period_end", "instant"})


def is_primary_context(context_id: str | None) -> bool:
    return bool(PRIMARY_CONTEXT.match(context_id or ""))
