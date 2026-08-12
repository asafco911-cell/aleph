"""Synthetic multi-company, multi-year data with KNOWN stories built in,
so the engine can be tested against answers we already know."""
from dataclasses import dataclass
from typing import List


@dataclass
class CompanyYear:
    company: str
    year: int
    revenue: float
    gross_profit: float
    rnd: float
    sga: float
    operating_income: float          # GAAP
    net_income: float                # GAAP
    adjusted_ebitda: float           # non-GAAP, definition may drift
    operating_cash_flow: float
    total_assets: float
    total_debt: float
    shares_diluted: float


# ALPHA: genuine, steady efficiency improvement. Margins expand every year.
ALPHA = [
    CompanyYear("ALPHA", 2021, 10000, 4000, 900, 2600, 500, 300, 900, 700, 12000, 3000, 1000),
    CompanyYear("ALPHA", 2022, 12000, 4920, 1020, 3000, 900, 600, 1400, 1100, 13500, 3000, 1005),
    CompanyYear("ALPHA", 2023, 14500, 6090, 1160, 3400, 1530, 1100, 2150, 1800, 15500, 2800, 1010),
    CompanyYear("ALPHA", 2024, 17400, 7482, 1310, 3900, 2272, 1700, 3050, 2600, 18000, 2600, 1015),
    CompanyYear("ALPHA", 2025, 20900, 9186, 1470, 4500, 3216, 2500, 4200, 3600, 21000, 2400, 1020),
]

# BETA: revenue grows but margins are FLAT. Growth without operating leverage.
BETA = [
    CompanyYear("BETA", 2021, 8000, 2800, 600, 1800, 400, 250, 700, 600, 9000, 2000, 800),
    CompanyYear("BETA", 2022, 9600, 3360, 720, 2160, 480, 300, 840, 700, 10500, 2200, 810),
    CompanyYear("BETA", 2023, 11500, 4025, 863, 2588, 574, 360, 1006, 850, 12500, 2500, 820),
    CompanyYear("BETA", 2024, 13800, 4830, 1035, 3105, 690, 430, 1207, 1000, 15000, 2900, 830),
    CompanyYear("BETA", 2025, 16600, 5810, 1245, 3735, 830, 520, 1452, 1200, 18000, 3400, 840),
]

# GAMMA: GAAP profit stalls, but adjusted EBITDA JUMPS in 2023 -- definition change.
GAMMA = [
    CompanyYear("GAMMA", 2021, 6000, 2100, 500, 1300, 300, 180, 500, 400, 7000, 1500, 600),
    CompanyYear("GAMMA", 2022, 6600, 2310, 560, 1450, 300, 175, 550, 390, 7600, 1700, 610),
    CompanyYear("GAMMA", 2023, 7100, 2485, 600, 1560, 325, 170, 1150, 400, 8200, 1900, 620),
    CompanyYear("GAMMA", 2024, 7600, 2660, 640, 1680, 340, 165, 1300, 410, 8900, 2200, 635),
    CompanyYear("GAMMA", 2025, 8100, 2835, 680, 1790, 365, 160, 1480, 420, 9700, 2600, 650),
]

ALL_DATA: List[CompanyYear] = ALPHA + BETA + GAMMA