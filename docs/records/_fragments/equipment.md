Lab equipment follows the same spec + instance pattern: the **equipment
spec** is the product (a cycler model, its channel count, supported
chemistries), the **equipment** record is one physical unit (serial number,
location, status), and a **channel** is one addressable slot on a unit —
its uid is deterministic from (unit, index), so re-registering a bench never
duplicates channels. Tests point at the unit and channel they ran on through
`equipment_id` and `channel_id`.
