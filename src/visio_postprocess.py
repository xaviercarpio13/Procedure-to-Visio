
from pathlib import Path
import shutil
import pythoncom
import win32com.client


LABEL_WIDTH = 0.42   # width of the dark gray strip in inches
LEFT_PADDING = 0.02  # minimum left page margin


def _norm(text):
    return " ".join((text or "").split()).strip()


def _safe_set_formula(shape, cell_name, formula):
    try:
        shape.CellsU(cell_name).FormulaU = formula
    except Exception:
        pass


def _safe_set_result(shape, cell_name, value):
    try:
        shape.CellsU(cell_name).ResultIU = value
    except Exception:
        pass


def _walk_shapes(shapes):
    for shape in shapes:
        yield shape
        try:
            if shape.Shapes.Count > 0:
                yield from _walk_shapes(shape.Shapes)
        except Exception:
            pass


def _get_shape_box(shape):
    """
    Returns: (left, right, bottom, top)
    """
    x = shape.CellsU("PinX").ResultIU
    y = shape.CellsU("PinY").ResultIU
    w = shape.CellsU("Width").ResultIU
    h = shape.CellsU("Height").ResultIU

    return (
        x - w / 2,
        x + w / 2,
        y - h / 2,
        y + h / 2,
    )


def _find_lane_shape(page, lane_name):
    """
    Find the actual swimlane/container shape whose text is the lane name.
    We pick the widest matching shape, because the lane body is usually the widest.
    """
    lane_target = _norm(lane_name).lower()
    best_shape = None
    best_width = -1

    for shape in _walk_shapes(page.Shapes):
        try:
            text = _norm(shape.Text).lower()
        except Exception:
            continue

        if not text:
            continue

        if text == lane_target or lane_target in text or text in lane_target:
            try:
                left, right, bottom, top = _get_shape_box(shape)
                width = right - left
            except Exception:
                continue

            if width > best_width:
                best_width = width
                best_shape = shape

    return best_shape


def _clear_existing_lane_text(shape):
    try:
        shape.Text = ""
    except Exception:
        pass


def _font_size_for_lane_name(lane_name):
    """
    Smaller font for longer names.
    """
    length = len(lane_name)

    if length >= 42:
        return "5 pt"
    if length >= 30:
        return "6 pt"
    return "7 pt"


def _draw_lane_strip(page, lane_left, y_bottom, y_top):
    """
    Draws the dark gray strip flush against the left side of the swimlane.
    """
    strip_right = lane_left
    strip_left = max(LEFT_PADDING, strip_right - LABEL_WIDTH)

    bg = page.DrawRectangle(
        strip_left,
        y_bottom,
        strip_right,
        y_top
    )

    bg.Text = ""
    _safe_set_formula(bg, "FillForegnd", "RGB(70,70,70)")
    _safe_set_formula(bg, "FillPattern", "1")
    _safe_set_formula(bg, "LineColor", "RGB(70,70,70)")
    _safe_set_formula(bg, "LineWeight", "0.5 pt")

    return strip_left, strip_right, bg


def _draw_rotated_lane_text(page, lane_name, strip_left, strip_right, y_bottom, y_top):
    """
    Draw a transparent text box on top of the dark strip.

    Important:
    - The shape itself stays the same size as the strip.
    - Only the text block is rotated using TxtAngle.
    - TxtWidth is set to the lane height, so text has enough room.
    """
    lane_height = y_top - y_bottom
    strip_width = strip_right - strip_left

    text_box = page.DrawRectangle(
        strip_left,
        y_bottom,
        strip_right,
        y_top
    )

    text_box.Text = lane_name

    # Keep the shape aligned with the dark strip
    _safe_set_formula(text_box, "Angle", "0 deg")

    # Transparent / no border
    _safe_set_formula(text_box, "FillPattern", "0")
    _safe_set_formula(text_box, "LinePattern", "0")

    # Rotate ONLY the internal text block
    _safe_set_formula(text_box, "TxtAngle", "90 deg")

    # Give the rotated text enough space
    _safe_set_result(text_box, "TxtWidth", max(lane_height - 0.10, 0.5))
    _safe_set_result(text_box, "TxtHeight", max(strip_width - 0.05, 0.15))

    # Center the internal text block inside the shape
    _safe_set_formula(text_box, "TxtPinX", "Width*0.5")
    _safe_set_formula(text_box, "TxtPinY", "Height*0.5")
    _safe_set_formula(text_box, "TxtLocPinX", "TxtWidth*0.5")
    _safe_set_formula(text_box, "TxtLocPinY", "TxtHeight*0.5")

    # Text style
    _safe_set_formula(text_box, "Char.Size", _font_size_for_lane_name(lane_name))
    _safe_set_formula(text_box, "Char.Style", "1")
    _safe_set_formula(text_box, "Para.HorzAlign", "1")
    _safe_set_formula(text_box, "VerticalAlign", "1")
    _safe_set_formula(text_box, "Char.Color", "RGB(255,255,255)")

    text_box.BringToFront()

    return text_box


def move_lane_labels_to_left(vsdx_path, lane_names):
    original_path = Path(vsdx_path).resolve()
    fixed_path = original_path.with_name(original_path.stem + "_fixed.vsdx")

    shutil.copy2(original_path, fixed_path)

    pythoncom.CoInitialize()

    visio = None
    doc = None

    try:
        visio = win32com.client.DispatchEx("Visio.Application")
        visio.Visible = False

        doc = visio.Documents.Open(str(fixed_path))
        page = doc.Pages.Item(1)

        created = 0
        cleared = 0

        for lane_name in lane_names:
            lane_shape = _find_lane_shape(page, lane_name)

            if lane_shape is None:
                print(f"LANE_NOT_FOUND={lane_name}")
                continue

            left, right, y_bottom, y_top = _get_shape_box(lane_shape)

            # remove original centered lane text
            if _norm(lane_shape.Text):
                _clear_existing_lane_text(lane_shape)
                cleared += 1

            # draw dark strip with EXACT same height as lane shape
            strip_left, strip_right, bg = _draw_lane_strip(
                page,
                lane_left=left,
                y_bottom=y_bottom,
                y_top=y_top
            )

            bg.BringToFront()

            # draw rotated vertical text on top
            text_box = _draw_rotated_lane_text(
                page,
                lane_name,
                strip_left,
                strip_right,
                y_bottom,
                y_top
            )
            text_box.BringToFront()

            created += 1

        doc.SaveAs(str(fixed_path))



        return fixed_path

    finally:
        if doc is not None:
            doc.Close()

        if visio is not None:
            visio.Quit()

        pythoncom.CoUninitialize()