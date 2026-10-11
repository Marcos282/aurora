from django import forms

from .models import Advertiser


class ProfileForm(forms.ModelForm):
    contact_consent = forms.BooleanField(required=False, label="Autorizo exibir este contato publicamente.")

    class Meta:
        model = Advertiser
        fields = ["name", "age", "state", "city", "neighborhood", "summary", "description", "contact", "contact_consent", "available"]
        labels = {"description": "Descricao", "summary": "Resumo", "contact": "Contato publico", "age": "Idade (18 ou mais)"}
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def clean(self):
        data = super().clean()
        if data.get("contact") and not data.get("contact_consent"):
            self.add_error("contact_consent", "Autorize a publicacao do contato ou deixe-o vazio.")
        return data
