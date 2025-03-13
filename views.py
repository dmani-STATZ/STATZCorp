from django.shortcuts import render

def example_view(request):
    """
    Example view that demonstrates the use of custom Tailwind CSS colors.
    """
    return render(request, 'example.html') 