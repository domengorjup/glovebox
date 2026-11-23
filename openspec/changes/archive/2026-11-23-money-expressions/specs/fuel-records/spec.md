## ADDED Requirements

### Requirement: Calculations in the cost fields of a refuelling
The Total and Price per litre fields of the refuelling forms (quick and full) SHALL accept, besides a number, a simple calculation: an optional leading `=`; numbers with a decimal comma or point; `+ - * /` with the usual precedence; unary minus; parentheses; spaces ignored; at most 200 characters. It SHALL be evaluated exactly and rounded half up to the field's decimals (cents for the total, thousandths for the price per litre). A plain number SHALL be read exactly as before; a calculation has no limit on decimals. Litres and odometer SHALL NOT accept calculations. A malformed calculation SHALL be refused with "<Field>: Not a valid calculation." and a division by zero with "<Field>: Can't divide by zero.", the typed text kept and nothing stored. The page SHALL replace a valid calculation by its result when the field is left, and the two-of-three calculation SHALL use that result.

#### Scenario: Total as a calculation
- **WHEN** the user enters 40 L and the total `=30.5+30.5*2`
- **THEN** the record is stored with total 91.50 € and the price per litre derived from it

#### Scenario: Price per litre with a decimal comma
- **WHEN** the user enters 40 L and the price per litre `1,5+0.05`
- **THEN** the record is stored with price 1.550 €/L and total 62.00 €

#### Scenario: Calculation rounds to cents
- **WHEN** the user enters the total `1,299*0,75` (0.97425)
- **THEN** the total is stored as 0.97 €

#### Scenario: Division by zero
- **WHEN** the total is `10/0`
- **THEN** nothing is stored and the field shows "Total: Can't divide by zero." with the typed text kept

#### Scenario: Malformed calculation
- **WHEN** the total is `1+` or `(1+2`
- **THEN** nothing is stored and the field shows "Total: Not a valid calculation."

#### Scenario: Page replaces the calculation
- **WHEN** the user types `12+3` in Total and leaves the field
- **THEN** the field shows 15.00 and the two-of-three calculation uses 15
