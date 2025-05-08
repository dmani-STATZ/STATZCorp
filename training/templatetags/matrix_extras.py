from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)

@register.filter
def map_course_ids(matrix_entries):
    """Returns a list of course IDs from matrix entries"""
    return [entry.course.id for entry in matrix_entries]

@register.filter
def get_matrix_entry(matrix_entries, course_id):
    """Returns the matrix entry for a given course ID"""
    for entry in matrix_entries:
        if entry.course.id == course_id:
            return entry
    return None