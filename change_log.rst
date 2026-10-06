Change Log
==========

20.0.2.1 (2026-10-06)
---------------------

* Record Filter is now chosen by clicking, not typed by hand.
* Changing the Model now also clears the Date Field and Record Filter.
* Checking the filter now uses one shared method in the code.
* Record Filter help text no longer mentions one specific model.

20.0.2.0 (2026-10-06)
---------------------

* Lock now works on any model, not only account.move.
* Admin chooses Model, Method Name and Date Field in the rule.
* Method Name is a text field and is checked when you save.
* Removed the account dependency. Only base is needed now.
* Removed models/account_move.py.
* Added optional Record Filter.

20.0.1.0 (2026-10-05)
---------------------

* First version for account.move only.
* Admin sets users, method and lock date.
* Shows an error popup when the date is on or before the lock date.