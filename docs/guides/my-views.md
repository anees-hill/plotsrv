# My views

My views saves a table or plot presentation on the current browser. It does not
save data or create a server-side view, account or shared dashboard.

Change the search, filters, sorting, grouping, columns or plot settings, then
choose **+ My views** beside **Reset changes**. The save action is disabled until
meaningful settings differ from the presentation you opened. Enter a name and
an optional caption. This works with rich tables, stream table/plot explorers
and rectangular JSON tables. Images and other sources without adjustable table
or plot settings have no save action.

Open the source selector and choose **My views**. **Grouped** and **A–Z** still
contain the ordinary sources; Featured stays inside Grouped. Saved presentations
show their caption and identify unavailable sources. A missing source does not
delete its saved settings, and the selector remains available when the server's
catalogue is empty.

Opening a saved presentation marks it as active. After editing, choose
**Save changes…**, then **Update** or **Save as new**. Cancel leaves the saved
configuration untouched. **Reset changes** restores an active saved presentation;
for ordinary or incompatible presentations it returns to ordinary table/plot
defaults. Use the small **×** beside a saved entry to delete it. Confirmation
explains that only this browser's saved configuration is deleted, never data.

## Changing data and historical browsing

Saved settings apply to the source's **latest data**. Saving while browsing a
snapshot or stream session saves the presentation only; the dialog explains
this. Opening that saved entry starts at the latest source. Snapshot/session
selection remains a separate browsing choice, not part of the saved settings.

Extra columns are compatible. Missing grouping/sort/column settings can be
omitted with an explanation. Missing filters, changed filter types and invalid
plot fields pause the presentation rather than silently showing more rows or
a different plot under its saved name. **Repair presentation** asks you to
acknowledge the possible removal of filters. It applies compatible settings as
an ordinary working presentation; review the filters and plot before saving a
new view. The original saved configuration is preserved. Reset or reopen it
when the source is compatible again.

Compatibility checks use field names, lightweight inferred types and source
capabilities. They cannot detect changed units or meaning behind otherwise
identical fields; review presentations when the source semantics change.

A plot sourced from derived stream summaries retains that source requirement;
it cannot silently become a plot of retained raw rows. Existing plot limits and
coverage notices still apply. A saved presentation does not increase the source's
retention, query or plotting limits.

## Storage and compatibility

Settings are scoped to the browser origin, dashboard base path and configured
instance name, plus the exact logical source ID. Server restart generations are
not part of the storage key. Another browser profile, origin, base path or
instance name has a separate collection.

The collection is limited to 64 entries and 262,144 JSON characters; one ViewSpec
is limited to 16,384 characters, 128 fields/columns, 10 filters and 8 sort keys.
Names are at most 80 characters and captions 256. Storage is checked before JSON
parsing. Only supported presentation settings and lightweight field/type/source
requirements are accepted; datasets, paths, executable predicates, credentials,
DOM state and stream cursors are excluded.

Storage failures are visible in the dialog or selector. Disabled/full storage,
corrupt documents and unsupported versions do not silently replace existing
saves. This is the first ViewSpec format (version 1); unknown versions remain
untouched and need a compatible browser bundle. Other tabs receive change
notifications without replacing your working presentation. Updating a stale
copy is refused. Where Web Locks are available, saves across tabs are serialized
without waiting behind a busy tab; elsewhere the browser's normal last-write
behavior still applies to truly simultaneous writes.

These settings are browser preferences, not authenticated privacy or durable
backup. Filter values and captions may be sensitive; other users of this browser
profile can see them. Clearing site storage removes them. There is no cross-device
sync, server save/delete request, sharing or historical data binding.
