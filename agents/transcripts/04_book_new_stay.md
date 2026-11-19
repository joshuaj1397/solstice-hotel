# New booking: availability → hold (conversion path)

*Not signed in.*

**Guest:** Do you have a room in Austin from September 18 to 20, 2026?

> ⚙️ `check_availability` · Checking live availability
> 🗂️ card `check_availability`: `{"found": true, "property_code": "SOL-AUS", "property_name": "Solstice Austin Congress Ave", "city": "Austin", "check_in": "2026-09-18", "check_out": "2026-09-20", "nights": 2, "rate_plan": "Best Available Rate", "options": [{"room_type": "Accessible King", "a…`

**Sol:** I do have availability in Austin from September 18 to September 20, 2026. We have options including Accessible King, Standard Double, Standard King, Deluxe King, and Suite rooms. Would you like me to hold one of these for you?

<sub>699 ms · path `llm` · tools ['check_availability']</sub>

**Guest:** Yes please, hold the Standard King.

> ⚙️ `hold_room` · Holding your room
> 🗂️ card `hold_room`: `{"hold_id": "17067b3c-131d-427d-93cb-8c144728bdc3", "property_code": "SOL-AUS", "property_name": "Solstice Austin Congress Ave", "room_type": "Standard King", "check_in": "2026-09-18", "check_out": "2026-09-20", "nights": 2, "nightly_rate": 199.0, "total_befor…`

**Sol:** I have successfully placed a 15-minute hold on a Standard King room for you at the Solstice Austin Congress Ave from September 18 to September 20, 2026. Please complete your booking using the secure checkout button in the app to finalize it.

<sub>657 ms · path `llm` · tools ['hold_room']</sub>
