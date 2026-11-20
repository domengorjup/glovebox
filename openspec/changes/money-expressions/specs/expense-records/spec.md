## ADDED Requirements

### Requirement: Calculations in the amount field
The Amount field of the expense and service forms (quick and full) SHALL accept a calculation under the same rules as the cost fields of a refuelling (optional leading `=`, `+ - * /`, unary minus, parentheses, spaces ignored, at most 200 characters), evaluated exactly and rounded half up to cents. A plain number SHALL be read exactly as before. A malformed calculation SHALL be refused with "Amount: Not a valid calculation." and a division by zero with "Amount: Can't divide by zero.", the typed text kept and nothing stored. The page SHALL replace a valid calculation by its result when the field is left.

#### Scenario: Amount as a calculation
- **WHEN** the user enters the amount `=120 + 45,50 - 10`
- **THEN** the expense is stored with amount 155.50 €

#### Scenario: Parentheses
- **WHEN** the user enters the amount `=(100+20)*2`
- **THEN** the expense is stored with amount 240.00 €

#### Scenario: Division by zero
- **WHEN** the user enters the amount `=5/0`
- **THEN** the expense is rejected with "Amount: Can't divide by zero." and nothing is stored
