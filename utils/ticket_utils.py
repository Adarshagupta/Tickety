import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
import io
import base64

def generate_qr_code(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img_buffer = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(img_buffer, format='PNG', optimize=True)
    img_str = base64.b64encode(img_buffer.getvalue()).decode()
    return f'data:image/png;base64,{img_str}'

def generate_barcode(data):
    barcode_buffer = io.BytesIO()
    Code128(data, writer=ImageWriter()).write(
        barcode_buffer,
        options={
            'module_width': 0.2,
            'module_height': 15,
            'quiet_zone': 1,
            'font_size': 10,
            'text_distance': 5,
            'background': 'white',
            'foreground': 'black',
        }
    )
    img_str = base64.b64encode(barcode_buffer.getvalue()).decode()
    return f'data:image/png;base64,{img_str}' 