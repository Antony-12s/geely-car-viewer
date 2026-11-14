"""H.264 packets -> scaled PIL images.

Software decode only: measured 32% of one core for 2560x1600@30 into 704x440 (PyAV,
i5-12450H). The PyAV wheels ship no VAAPI/D3D11/VideoToolbox, and the CPU cost is
already low, so hardware decoding is not worth a platform-specific path.

It is also a stability rule on Linux: a 12th-gen Intel i915 GPU hung the whole desktop
("vebox forcewake" timeouts) under sustained use, so the decoder must never open
/dev/dri. HWACCEL stays None and the context is created without one, explicitly.
"""
import av
from PIL import Image

HWACCEL = None  # never a hardware device: see the module docstring


class Decoder:
    def __init__(self):
        self.ctx = av.CodecContext.create("h264", "r", hwaccel=HWACCEL)
        if getattr(self.ctx, "is_hwaccel", False):  # defensive: a future PyAV must not switch it on by itself
            raise RuntimeError("hardware video decoding is not allowed")
        # not AUTO: frame threading holds 12 frames back (~400 ms lag); SLICE adds none
        self.ctx.thread_type = "SLICE"

    def decode(self, data):
        return self.ctx.decode(av.Packet(data))

    @staticmethod
    def to_image(frame, width, height, rotate180=False, preserve_aspect=False):
        if preserve_aspect:
            scale = min(width / frame.width, height / frame.height)
            width, height = max(1, round(frame.width * scale)), max(1, round(frame.height * scale))
        # one swscale pass does colour conversion and the downscale together
        image = frame.reformat(width=width, height=height, format="rgb24", interpolation="FAST_BILINEAR").to_image()
        return image.transpose(Image.Transpose.ROTATE_180) if rotate180 else image
