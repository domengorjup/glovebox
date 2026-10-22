## MODIFIED Requirements

### Requirement: Backup tables
The standard format SHALL also define `vehicles.csv` (`name`, `make`, `model`, `plate`, `fuel_type`, `initial_odometer_km`, `archived`, `notes`, `vin`, `model_year`, `engine`, `tyre_size`, `insurance_policy`, `insurance_valid_until`, `registration_valid_until`) and `stations.csv` (`name`, `location`, `brand`), with the same file and value conventions. The columns added after `notes` are optional. Records SHALL refer to vehicles by name and to stations by name and location.

#### Scenario: Unused station listed
- **WHEN** a station has no refuels and a full backup is made
- **THEN** `stations.csv` contains it

#### Scenario: Vehicle details in a backup
- **WHEN** a vehicle with a VIN and an insurance date is backed up
- **THEN** `vehicles.csv` has them in the `vin` and `insurance_valid_until` columns, and the data package descriptor lists the columns
