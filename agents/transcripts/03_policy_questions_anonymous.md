# Policy questions without signing in

*Not signed in.*

**Guest:** What time is check-in?

> 🧭 *Router:* policy topic → `lookup_policy`
> ⚙️ `lookup_policy` · Checking Solstice policy
> 🗂️ card `lookup_policy`: `{"found": true, "sections": [{"policy": 1, "title": "CHECK-IN AND CHECK-OUT TIMES", "text": "Standard check-in is 3:00 PM and standard check-out is 11:00 AM. Early check-in and late check-out are both based on same-day room availability. Neither one is guarant…`

**Sol:** Standard check-in is at 3:00 PM. Early check-in and late check-out are based on same-day room availability and are at the front desk's discretion. Is there anything else I can assist you with regarding your stay?

<sub>504 ms · path `llm` · tools ['lookup_policy']</sub>

**Guest:** Can I bring my dog? He's a service animal.

> 🧭 *Router:* policy topic → `lookup_policy`
> ⚙️ `lookup_policy` · Checking Solstice policy
> 🗂️ card `lookup_policy`: `{"found": true, "sections": [{"policy": 8, "title": "PETS AND SERVICE ANIMALS", "text": "Pets are not permitted at any Solstice property, no exceptions, no pet-friendly floors. Service animals, as defined under the ADA, are always welcome and stay free of char…`

**Sol:** Service animals are always welcome and stay free of charge at our properties. Please let the front desk know what task your service animal is trained to perform. Is there anything else I can help you with today?

<sub>523 ms · path `llm` · tools ['lookup_policy']</sub>

**Guest:** How much is parking at the Chicago hotel?

> 🧭 *Router:* policy topic → `lookup_policy`
> ⚙️ `property_info` · Looking up the hotel
> 🗂️ card `property_info`: `{"found": true, "property_code": "SOL-CHI", "property_name": "Solstice Chicago Riverwalk", "city": "Chicago", "state": "IL", "market_type": "Urban", "total_rooms": 220, "max_meeting_capacity": 300, "meeting_space_sqft": 8500, "room_types": [{"room_type": "Acce…`

**Sol:** I do not have the specific parking rates for the Solstice Chicago Riverwalk. I recommend calling the front desk directly for that information.

<sub>374 ms · path `llm` · tools ['property_info']</sub>
