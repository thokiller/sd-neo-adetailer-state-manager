__version__ = "1.0.0"

EXT_NAME = "ADetailer State Manager"

TAB_NAMES = ("txt2img", "img2img")

PROFILE_IMG2IMG = "img2img"
PROFILE_INPAINT = "inpaint"

# elem_id of every img2img sub-tab, mapped onto the profile it belongs to.
# Grouping follows the "family" model: the plain/sketch/batch tabs share one
# configuration, the three inpainting tabs share another.
IMG2IMG_TAB_PROFILES = {
    "img2img_img2img_tab": PROFILE_IMG2IMG,
    "img2img_img2img_sketch_tab": PROFILE_IMG2IMG,
    "img2img_batch_tab": PROFILE_IMG2IMG,
    "img2img_inpaint_tab": PROFILE_INPAINT,
    "img2img_inpaint_sketch_tab": PROFILE_INPAINT,
    "img2img_inpaint_upload_tab": PROFILE_INPAINT,
}

PROFILE_LABELS = {
    PROFILE_IMG2IMG: "img2img",
    PROFILE_INPAINT: "Inpaint",
}
