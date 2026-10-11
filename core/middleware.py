from django.shortcuts import redirect


class AdultAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        excluded = ("/maioridade/", "/termos/", "/privacidade/", "/admin/", "/static/", "/robots.txt", "/sitemap.xml", "/pagamentos/webhook/")
        if not request.path.startswith(excluded) and not request.session.get("adult_confirmed"):
            return redirect("age-gate")
        return self.get_response(request)
