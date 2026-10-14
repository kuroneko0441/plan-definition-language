# 정산서

## 시간 규칙

- 정산서는 연 날보다 먼저 닫히지 않는다.
- 정산서는 정산월 안에 연다.

## 권한 규칙

- 회계 담당자는 정산서를 총금액 조회할 수 있다.

## 상태 판정 규칙

- 총금액은 정산서의 계산값(Money)이며 정산 행의 금액, 조정의 금액에서 계산한다.
  - 근거: 합계 금액은 칼럼으로 저장하지 않고 행과 조정에서 항상 계산한다.
- 행 구성은 정산서에 속한 정산 행들의 행 구분이 모두 같으면 그 값이고, 서로 다르면 '혼합'이다.

## 화면

- 정산서별 총금액은 정산서의 정산월, 총금액, 행 구성을 보여 준다.

## 부록

아래는 개발자를 위한 정리이다.
기본 자료형은 Text(글자), Int(정수), Decimal(소수), Money(금액), Bool(참 또는 거짓), Timestamp(시각), Duration(기간), Day(일), Week(주), Month(월)이다. 시간 값은 next(다음), before(이전), month_of(일이 속한 월)로 계산하고, 자료형 뒤의 물음표는 비어 있을 수 있음을, list는 여러 개를 뜻한다.

### 식

- closes_after_opening: `Settlement.opened_on <= Settlement.closed_on`
- opens_in_its_month: `month_of(Settlement.opened_on) = Settlement.month`

### 열거형

| 이름 | 값 | 근거 |
|---|---|---|
| 행 구분 (Kind) | Sale (판매), Return (반품) | - |

### 엔티티

| 이름 | 유일성 키 | 필드 | 근거 |
|---|---|---|---|
| 정산서 (Settlement) | id | id: Text<br>month (정산월): Month<br>opened_on: Day<br>closed_on: Day? | - |
| 정산 행 (SettlementRow) | - | settlement: Settlement<br>kind: Kind<br>amount (금액): Money | - |
| 조정 (Adjustment) | - | settlement: Settlement<br>amount (금액): Money<br>reason: Text | - |

### 권한 요약

조건부는 행 상태나 업로드 상태 같은 조건에 따라 허용 여부가 달라진다는 뜻이며, 조건은 위의 규칙 문장을 따른다.

- 회계 담당자: 정산서 총금액 조회 허용
