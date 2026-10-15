# West WX Watchers — BoM warnings relay

Every 5 minutes this repository fetches Western Australia's **Severe Thunderstorm**, **Severe Weather** and
**Tropical Cyclone** warnings from the Bureau of Meteorology's anonymous FTP server
(`ftp.bom.gov.au/anon/gen/fwo`, BoM's free public channel for warning products) and writes
[`data/warnings.json`](data/warnings.json) for [westweatherwatchers.com](https://westweatherwatchers.com).

* Tropical cyclone watch/warning areas are BoM's own polygons.
* Severe thunderstorm and severe weather areas are **approximate**: an outline drawn around the
  locations listed in each warning, trimmed to the named forecast districts.
* The official BoM warning image is kept (unaltered) while a warning is current.

**This is not an official warning service.** Always check [www.bom.gov.au](https://www.bom.gov.au) and
[Emergency WA](https://www.emergency.wa.gov.au).

Warnings © Commonwealth of Australia, Bureau of Meteorology. Place names: [GeoNames](https://www.geonames.org) (CC BY 4.0).
District boundaries: BoM forecast districts (IDM00001).
