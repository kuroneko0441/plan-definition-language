# 주문

기획 수준: 확정

## 업무 흐름: 주문 진행

```mermaid
stateDiagram-v2
    state "작성 중" as Draft
    state "결제됨" as Paid
    state "취소됨" as Cancelled
    [*] --> Draft
    Draft --> Paid: 결제 (결제 대행사)
    Draft --> Cancelled: 취소 (구매자)
    Paid --> [*]
    Cancelled --> [*]
```

- 처음: 작성 중
- 끝: 결제됨, 취소됨
- 건마다 따로 진행되는 대상: 주문

- '작성 중' 상태에서 this.buyer.standing가 'Active'일 때 '결제'가 일어나면 '결제됨' 상태가 된다. (주체: 결제 대행사)
- '작성 중' 상태에서 '취소'가 일어나면 '취소됨' 상태가 된다. (주체: 구매자)
- 위에 적은 경우가 아니면 다음 사건은 받아들이지 않는다: '결제', '취소'
  - 근거: 정지된 회원의 결제는 받지 않는다.

## 검증한 성질

- 결제된 주문의 구매자는 모두 정상 회원이다.
- 두 주문이 모두 결제되는 경우가 있다.
- 한 주문의 결제는 다른 주문의 취소를 막지 않는다.

## 부록

아래는 개발자를 위한 정리이다.
기본 자료형은 Text(글자), Int(정수), Decimal(소수), Money(금액), Bool(참 또는 거짓), Timestamp(시각), Duration(기간), Day(일), Week(주), Month(월)이다. 시간 값은 next(다음), before(이전), month_of(일이 속한 월)로 계산하고, 자료형 뒤의 물음표는 비어 있을 수 있음을, list는 여러 개를 뜻한다.

### 식

- paid_by_active: `always ∀ o ∈ Order : o.Flow = Paid ⇒ o.buyer.standing = Active`
- all_can_be_paid: `reachable ∀ o ∈ Order : o.Flow = Paid`
- independent: `reachable Order1.Flow = Paid ∧ Order2.Flow = Cancelled`

### 열거형

| 이름 | 값 | 근거 |
|---|---|---|
| 회원 상태 (Standing) | Active (정상), Suspended (정지) | - |

### 엔티티

| 이름 | 유일성 키 | 필드 | 근거 |
|---|---|---|---|
| 회원 (Member) | id | id: Text<br>standing: Standing [변하지 않음] | - |
| 주문 (Order) | id | id: Text<br>buyer (구매자): Member [변하지 않음] | - |
