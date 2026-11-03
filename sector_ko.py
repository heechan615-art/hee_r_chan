"""S&P500 GICS 섹터·세부 업종(Sub-Industry) 한국어 이름 — 주도 섹터 찾기 탭(sector.py)용"""
SECTOR_KO = {
    "Information Technology": "IT(기술)", "Communication Services": "커뮤니케이션", "Consumer Discretionary": "경기소비재",
    "Financials": "금융", "Industrials": "산업재", "Materials": "소재", "Energy": "에너지", "Health Care": "헬스케어",
    "Consumer Staples": "필수소비재", "Utilities": "유틸리티", "Real Estate": "부동산",
}
SUB_KO = {
    # 커뮤니케이션
    "Advertising": "광고", "Broadcasting": "방송", "Cable & Satellite": "케이블·위성", "Integrated Telecommunication Services": "통신사",
    "Interactive Home Entertainment": "게임", "Interactive Media & Services": "인터넷 플랫폼", "Movies & Entertainment": "영화·엔터테인먼트",
    "Publishing": "출판", "Wireless Telecommunication Services": "무선 통신",
    # 경기소비재
    "Apparel Retail": "의류 소매", "Apparel, Accessories & Luxury Goods": "의류·명품", "Automobile Manufacturers": "자동차",
    "Automotive Parts & Equipment": "자동차 부품", "Automotive Retail": "자동차 판매", "Broadline Retail": "온라인·종합 소매",
    "Casinos & Gaming": "카지노", "Computer & Electronics Retail": "전자제품 소매", "Consumer Electronics": "가전",
    "Distributors": "유통", "Footwear": "신발", "Home Improvement Retail": "주택 개조 소매", "Homebuilding": "주택 건설",
    "Homefurnishing Retail": "가구 소매", "Hotels, Resorts & Cruise Lines": "호텔·크루즈", "Leisure Products": "레저용품",
    "Other Specialty Retail": "전문 소매", "Restaurants": "외식", "Specialized Consumer Services": "생활 서비스",
    # 필수소비재
    "Agricultural Products & Services": "농산물", "Consumer Staples Merchandise Retail": "할인점", "Distillers & Vintners": "주류",
    "Food Distributors": "식품 유통", "Food Retail": "식품 소매", "Household Products": "생활용품", "Packaged Foods & Meats": "가공식품",
    "Personal Care Products": "개인 위생용품", "Soft Drinks & Non-alcoholic Beverages": "음료", "Tobacco": "담배",
    # 에너지
    "Integrated Oil & Gas": "종합 석유", "Oil & Gas Equipment & Services": "유전 장비·서비스", "Oil & Gas Exploration & Production": "석유 탐사·생산",
    "Oil & Gas Refining & Marketing": "정유", "Oil & Gas Storage & Transportation": "석유 저장·운송",
    # 금융
    "Asset Management & Custody Banks": "자산운용·수탁", "Consumer Finance": "소비자 금융", "Diversified Banks": "대형 은행",
    "Financial Exchanges & Data": "거래소·금융 데이터", "Insurance Brokers": "보험 중개", "Investment Banking & Brokerage": "투자은행·증권",
    "Life & Health Insurance": "생명·건강보험", "Multi-Sector Holdings": "지주사", "Multi-line Insurance": "종합 보험",
    "Property & Casualty Insurance": "손해보험", "Regional Banks": "지역 은행", "Reinsurance": "재보험",
    "Transaction & Payment Processing Services": "결제",
    # 헬스케어
    "Biotechnology": "바이오", "Health Care Distributors": "의약품 유통", "Health Care Equipment": "의료기기",
    "Health Care Facilities": "병원", "Health Care Services": "의료 서비스", "Health Care Supplies": "의료 소모품",
    "Health Care Technology": "헬스케어 IT", "Life Sciences Tools & Services": "생명과학 장비", "Managed Health Care": "건강보험(관리의료)",
    "Pharmaceuticals": "제약",
    # 산업재
    "Aerospace & Defense": "항공우주·방산", "Agricultural & Farm Machinery": "농기계", "Air Freight & Logistics": "항공 화물·물류",
    "Building Products": "건축 자재", "Cargo Ground Transportation": "육상 화물", "Construction & Engineering": "건설·엔지니어링",
    "Construction Machinery & Heavy Transportation Equipment": "건설기계·중장비", "Data Processing & Outsourced Services": "데이터 처리·아웃소싱",
    "Diversified Support Services": "기업 지원 서비스", "Electrical Components & Equipment": "전기 장비", "Environmental & Facilities Services": "환경·시설 관리",
    "Heavy Electrical Equipment": "중전기(발전 설비)", "Human Resource & Employment Services": "인력 서비스", "Industrial Conglomerates": "복합 기업",
    "Industrial Machinery & Supplies & Components": "산업 기계", "Passenger Airlines": "항공사", "Passenger Ground Transportation": "승객 운송",
    "Rail Transportation": "철도", "Research & Consulting Services": "리서치·컨설팅", "Trading Companies & Distributors": "산업재 유통",
    # IT
    "Application Software": "응용 소프트웨어", "Communications Equipment": "통신 장비", "Electronic Components": "전자 부품",
    "Electronic Equipment & Instruments": "전자 장비·계측", "Electronic Manufacturing Services": "전자제품 위탁생산", "IT Consulting & Other Services": "IT 컨설팅",
    "Internet Services & Infrastructure": "인터넷 인프라", "Semiconductor Materials & Equipment": "반도체 장비", "Semiconductors": "반도체",
    "Systems Software": "시스템 소프트웨어", "Technology Distributors": "IT 유통", "Technology Hardware, Storage & Peripherals": "하드웨어·저장장치",
    # 소재
    "Commodity Chemicals": "범용 화학", "Construction Materials": "건축 소재", "Copper": "구리", "Fertilizers & Agricultural Chemicals": "비료·농약",
    "Gold": "금", "Industrial Gases": "산업용 가스", "Metal, Glass & Plastic Containers": "용기", "Paper & Plastic Packaging Products & Materials": "포장재",
    "Specialty Chemicals": "특수 화학", "Steel": "철강",
    # 부동산
    "Data Center REITs": "데이터센터 리츠", "Health Care REITs": "헬스케어 리츠", "Hotel & Resort REITs": "호텔 리츠", "Industrial REITs": "물류 리츠",
    "Multi-Family Residential REITs": "임대주택 리츠", "Office REITs": "오피스 리츠", "Other Specialized REITs": "특수 리츠", "Real Estate Services": "부동산 서비스",
    "Retail REITs": "상가 리츠", "Self-Storage REITs": "창고 리츠", "Single-Family Residential REITs": "단독주택 리츠", "Telecom Tower REITs": "통신탑 리츠",
    "Timber REITs": "산림 리츠",
    # 유틸리티
    "Electric Utilities": "전력", "Gas Utilities": "가스", "Independent Power Producers & Energy Traders": "독립 발전", "Multi-Utilities": "복합 유틸리티",
    "Water Utilities": "수도",
}
