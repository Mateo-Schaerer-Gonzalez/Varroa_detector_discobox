"""The plate: its zones, the mites in them and their ids, and the names written
beside the plates.

    zones.py         the zones of the plates and the mites in each; mite ids (mite_ids())
    zone_masks.py    the zone masks: built in, and made on the Zones page; their coordinates files
    zone_layout.py   the zone mask a recording uses, saved with it
    slide_finder.py  finds the slides and the zone where their writing is (the automatic mask)
    mite.py          one detected mite: its box, scores and calls
    hand_mites.py    mites placed by hand where the detector missed them
    rect.py          a box in image pixels
    positions.py     which saved entry (ground truth, corrections, marks) belongs to which mite
    label_reader.py  reads the names written beside the plates (Google Gemini)
"""
