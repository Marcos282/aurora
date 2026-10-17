import warnings

from django import forms
from PIL import Image

from .models import Branding


class AccessForm(forms.Form):
    guest_name = forms.CharField(label='Nome do hóspede', max_length=100)
    username = forms.RegexField(
        label='Usuário do Hotspot', regex=r'\A[a-zA-Z0-9][a-zA-Z0-9._-]{2,39}\Z',
        min_length=3, max_length=40,
        help_text='De 3 a 40 caracteres: letras, números, ponto, hífen ou sublinhado.',
        widget=forms.TextInput(attrs={'autocomplete': 'off', 'autocapitalize': 'none', 'spellcheck': 'false'}),
    )
    password = forms.CharField(
        label='Senha do Hotspot', min_length=8, max_length=64, strip=False,
        help_text='De 8 a 64 caracteres. Esta é a senha do Wi-Fi, não a senha da sua conta.',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    duration_hours = forms.TypedChoiceField(
        label='Plano de acesso', coerce=int,
        choices=[(1, '1 hora'), (3, '3 horas'), (6, '6 horas')],
    )
    devices = forms.TypedChoiceField(label='Dispositivos simultâneos', choices=[(n, str(n)) for n in range(1, 7)], coerce=int)
    request_id = forms.UUIDField(widget=forms.HiddenInput)


class BrandingForm(forms.ModelForm):
    class Meta:
        model = Branding
        fields = ['welcome', 'wallpaper']
        widgets = {'wallpaper': forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'})}

    def clean_wallpaper(self):
        upload = self.cleaned_data.get('wallpaper')
        if not upload or not hasattr(upload, 'content_type'):
            return upload
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Envie uma imagem de até 5 MB.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                image = Image.open(upload)
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 16_000_000:
                    raise ValueError
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise forms.ValidationError('Use uma imagem JPEG, PNG ou WebP válida, de até 16 megapixels.') from None
        finally:
            upload.seek(0)
        return upload
