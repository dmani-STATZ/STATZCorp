document.addEventListener('DOMContentLoaded', () => {
    const portalState = JSON.parse(document.getElementById('portal-context-data').textContent);
    const announcementsElement = document.getElementById('portal-announcements-data');
    const initialAnnouncements = announcementsElement ? JSON.parse(announcementsElement.textContent) : [];
    const calendarElement = document.getElementById('workCalendar');
    const modalRegistry = {
        sectionModal: document.getElementById('sectionModal'),
        resourceModal: document.getElementById('resourceModal'),
        eventModal: document.getElementById('eventModal'),
        announcementModal: document.getElementById('announcementModal'),
    };
    const csrftoken = document.querySelector('#sectionForm [name=csrfmiddlewaretoken]')?.value ||
        document.querySelector('#resourceForm [name=csrfmiddlewaretoken]')?.value ||
        document.querySelector('#eventForm [name=csrfmiddlewaretoken]')?.value ||
        getCookie('csrftoken');
    const config = window.portalDashboardConfig || {};
    const urls = config.urls || {};
    let calendar;

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : '';
    }

    function toggleModal(id, show = true) {
        const modal = modalRegistry[id];
        if (!modal) return;
        modal.classList.toggle('hidden', !show);
        modal.classList.toggle('flex', show);
        if (show && id === 'eventModal') {
            prefillEventForm();
        }
    }

    function prefillEventForm() {
        const form = document.getElementById('eventForm');
        if (!form) return;
        const startField = form.querySelector('[name="start_at"]');
        const endField = form.querySelector('[name="end_at"]');
        if (!startField || !endField) return;
        const now = new Date();
        now.setMinutes(0, 0, 0);
        now.setHours(now.getHours() + 1);
        const end = new Date(now.getTime() + 60 * 60 * 1000);
        startField.value = now.toISOString().slice(0, 16);
        endField.value = end.toISOString().slice(0, 16);
    }

    function resourceDeleteUrl(id) {
        if (!urls.resourceDelete) return null;
        return urls.resourceDelete.replace('/0/', `/${id}/`);
    }

    function eventDeleteUrl(id) {
        if (!urls.eventDelete) return null;
        return urls.eventDelete.replace('/0/', `/${id}/`);
    }

    function computeEventColor(priority) {
        switch (priority) {
            case 'critical':
                return '#b91c1c';
            case 'high':
                return '#d97706';
            case 'low':
                return '#0f766e';
            default:
                return '#2563eb';
        }
    }

    function renderSections() {
        const table = document.getElementById('sectionTable');
        if (!table) return;
        const headRow = table.querySelector('thead tr');
        const bodyRow = table.querySelector('tbody tr');
        headRow.innerHTML = '';
        bodyRow.innerHTML = '';

        if (!portalState.sections.length) {
            const th = document.createElement('th');
            th.className = 'px-4 py-3 text-left text-sm font-semibold text-gray-500';
            th.textContent = 'No categories yet';
            headRow.appendChild(th);

            const td = document.createElement('td');
            td.className = 'px-4 py-6 text-sm text-center text-gray-500';
            td.textContent = 'Use "New Category" to get started.';
            bodyRow.appendChild(td);
            return;
        }

        portalState.sections.forEach((section, index) => {
            const th = document.createElement('th');
            th.className = 'px-4 py-3 text-left text-sm font-semibold text-gray-700';
            if (index !== portalState.sections.length - 1) {
                th.classList.add('border-r');
            }
            th.textContent = section.title || 'Untitled';
            headRow.appendChild(th);

            const td = document.createElement('td');
            td.className = 'align-top px-4 py-4';
            if (index !== portalState.sections.length - 1) {
                td.classList.add('border-r');
            }
            populateSectionColumn(td, section);
            bodyRow.appendChild(td);
        });
    }

    function populateSectionColumn(cell, section) {
        const list = document.createElement('ul');
        list.className = 'space-y-2';
        list.dataset.sectionId = section.id;

        const resources = section.resources || [];
        if (resources.length) {
            resources.forEach((resource) => {
                const li = document.createElement('li');
                li.className = 'flex items-start justify-between gap-2 resource-item';
                li.dataset.resourceId = resource.id;

                const link = document.createElement('a');
                link.href = resource.url || '#';
                if (resource.resource_type === 'file') {
                    link.target = '_blank';
                }
                link.className = 'text-sm text-blue-600 hover:underline';
                link.textContent = resource.title || 'Untitled file';
                li.appendChild(link);

                if (section.can_edit) {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'text-xs text-red-500 delete-resource';
                    button.dataset.resource = resource.id;
                    button.textContent = 'Remove';
                    li.appendChild(button);
                }

                list.appendChild(li);
            });
        } else {
            const empty = document.createElement('li');
            empty.className = 'text-sm text-gray-500';
            empty.textContent = 'No files yet.';
            list.appendChild(empty);
        }

        cell.appendChild(list);

        if (section.can_edit) {
            const addButton = document.createElement('button');
            addButton.type = 'button';
            addButton.className = 'mt-3 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 add-resource';
            addButton.dataset.section = section.id;
            addButton.dataset.sectionTitle = section.title || 'Untitled';
            addButton.textContent = '+ Add File';
            cell.appendChild(addButton);
        }
    }

    function renderAnnouncements(data) {
        const container = document.getElementById('announcementList');
        if (!container || !data?.announcements) return;
        container.innerHTML = '';
        if (!data.announcements.length) {
            const message = document.createElement('p');
            message.className = 'text-sm text-gray-500';
            message.textContent = 'No announcements posted.';
            container.appendChild(message);
            return;
        }

        data.announcements.forEach((item) => {
            const article = document.createElement('article');
            article.className = 'border border-gray-200 rounded-md px-3 py-2 bg-gray-50';

            const title = document.createElement('h3');
            title.className = 'text-sm font-semibold text-gray-800';
            title.textContent = item.title;
            article.appendChild(title);

            const content = document.createElement('p');
            content.className = 'text-sm text-gray-600 mt-1';
            content.textContent = item.content;
            article.appendChild(content);

            const meta = document.createElement('p');
            meta.className = 'text-xs text-gray-400 mt-2';
            const postedBy = item.posted_by ? ` by ${item.posted_by}` : '';
            meta.textContent = `Posted ${new Date(item.posted_at).toLocaleString()}${postedBy}`;
            article.appendChild(meta);

            container.appendChild(article);
        });
    }

    function initCalendar() {
        if (!calendarElement) return;
        calendar = new FullCalendar.Calendar(calendarElement, {
            initialView: 'dayGridMonth',
            height: 'auto',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,listWeek',
            },
            events: buildCalendarEvents(portalState.events || []),
            eventClick: handleEventClick,
        });
        calendar.render();
    }

    function buildCalendarEvents(events) {
        return (events || []).map((ev) => ({
            id: ev.id,
            title: ev.title,
            start: ev.start,
            end: ev.end,
            allDay: Boolean(ev.all_day),
            backgroundColor: computeEventColor(ev.priority),
            borderColor: 'transparent',
            extendedProps: ev,
        }));
    }

    function handleEventClick(info) {
        const props = info.event.extendedProps || {};
        const lines = [
            `Title: ${info.event.title}`,
            props.location ? `Location: ${props.location}` : null,
            `Starts: ${new Date(info.event.start).toLocaleString()}`,
            info.event.end ? `Ends: ${new Date(info.event.end).toLocaleString()}` : null,
            props.organizer_name ? `Created by: ${props.organizer_name}` : null,
        ].filter(Boolean).join('
');
        if (props.can_edit) {
            const confirmDelete = confirm(`${lines}

Delete this event?`);
            if (confirmDelete) {
                deleteEvent(info.event.id);
            }
        } else {
            alert(lines);
        }
    }

    async function deleteEvent(eventId) {
        const url = eventDeleteUrl(eventId);
        if (!url) return;
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken, 'Accept': 'application/json' },
            });
            if (response.ok) {
                refreshPortalData();
            }
        } catch (error) {
            console.error('Failed to delete event', error);
        }
    }

    async function refreshPortalData() {
        if (!urls.dashboard) return;
        try {
            const response = await fetch(urls.dashboard, { headers: { 'Accept': 'application/json' } });
            if (!response.ok) return;
            const data = await response.json();
            portalState.sections = data.sections || [];
            portalState.events = data.events || [];
            renderSections();
            renderAnnouncements(data);
            renderCalendarEvents();
        } catch (error) {
            console.error('Failed to refresh portal data', error);
        }
    }

    function renderCalendarEvents() {
        if (!calendar) return;
        calendar.removeAllEvents();
        buildCalendarEvents(portalState.events).forEach((event) => calendar.addEvent(event));
    }

    function attachModalTriggers() {
        document.querySelectorAll('[data-modal-target]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-modal-target');
                if (target === 'resourceModal' && btn.dataset.trigger === 'add-file-root') {
                    prepareResourceModal();
                }
                toggleModal(target, true);
            });
        });
        document.querySelectorAll('[data-close-modal]').forEach((btn) => {
            btn.addEventListener('click', () => {
                Object.keys(modalRegistry).forEach((id) => toggleModal(id, false));
            });
        });
        Object.values(modalRegistry).forEach((modal) => {
            modal?.addEventListener('click', (event) => {
                if (event.target === modal) {
                    toggleModal(modal.id, false);
                }
            });
        });
    }

    function prepareResourceModal(sectionId = null, sectionTitle = null) {
        const form = document.getElementById('resourceForm');
        if (!form) return;
        form.reset();
        const sectionField = form.querySelector('[name="section"]');
        if (sectionField) {
            if (sectionId) {
                sectionField.value = String(sectionId);
                sectionField.disabled = true;
            } else {
                sectionField.disabled = false;
            }
        }
        toggleResourceInputs(form);
        const heading = document.getElementById('resourceModalTitle');
        if (heading) {
            heading.textContent = sectionTitle ? `Add File to ${sectionTitle}` : 'Add File';
        }
    }

    function toggleResourceInputs(form) {
        if (!form) return;
        const typeField = form.querySelector('[name="resource_type"]');
        const fileInput = form.querySelector('[name="file"]');
        const urlInput = form.querySelector('[name="external_url"]');
        const fileWrapper = fileInput ? fileInput.closest('div') : null;
        const urlWrapper = urlInput ? urlInput.closest('div') : null;
        if (!typeField || !fileWrapper || !urlWrapper) return;
        const type = typeField.value;
        if (type === 'file') {
            fileWrapper.classList.remove('hidden');
            fileInput?.removeAttribute('disabled');
            fileInput?.setAttribute('required', 'required');
            urlWrapper.classList.add('hidden');
            urlInput?.setAttribute('disabled', 'disabled');
            urlInput?.removeAttribute('required');
            if (urlInput) urlInput.value = '';
        } else if (type === 'link') {
            urlWrapper.classList.remove('hidden');
            urlInput?.removeAttribute('disabled');
            urlInput?.setAttribute('required', 'required');
            fileWrapper.classList.add('hidden');
            fileInput?.setAttribute('disabled', 'disabled');
            fileInput?.removeAttribute('required');
            if (fileInput) fileInput.value = '';
        } else {
            fileWrapper.classList.remove('hidden');
            urlWrapper.classList.remove('hidden');
            fileInput?.removeAttribute('disabled');
            fileInput?.removeAttribute('required');
            urlInput?.removeAttribute('disabled');
            urlInput?.removeAttribute('required');
        }
    }

    function bindDynamicActions() {
        document.body.addEventListener('click', (event) => {
            const target = event.target;
            if (target.matches('.add-resource')) {
                const sectionId = target.getAttribute('data-section');
                const sectionTitle = target.getAttribute('data-section-title');
                prepareResourceModal(sectionId, sectionTitle);
                toggleModal('resourceModal', true);
            }
            if (target.matches('.delete-resource')) {
                const resourceId = target.getAttribute('data-resource');
                if (resourceId && confirm('Remove this file from the portal?')) {
                    deleteResource(resourceId);
                }
            }
        });
    }

    async function deleteResource(resourceId) {
        const url = resourceDeleteUrl(resourceId);
        if (!url) return;
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken, 'Accept': 'application/json' },
            });
            if (response.ok) {
                refreshPortalData();
            }
        } catch (error) {
            console.error('Failed to delete resource', error);
        }
    }

    function bindForms() {
        const sectionForm = document.getElementById('sectionForm');
        sectionForm?.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!urls.sections) return;
            const formData = new FormData(sectionForm);
            const response = await fetch(urls.sections, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken },
                body: formData,
            });
            if (response.ok) {
                toggleModal('sectionModal', false);
                sectionForm.reset();
                refreshPortalData();
            }
        });

        const resourceForm = document.getElementById('resourceForm');
        if (resourceForm) {
            const typeField = resourceForm.querySelector('[name="resource_type"]');
            typeField?.addEventListener('change', () => toggleResourceInputs(resourceForm));
            toggleResourceInputs(resourceForm);
        }
        resourceForm?.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!urls.resourceUpsert) return;
            const formData = new FormData(resourceForm);
            const sectionField = resourceForm.querySelector('[name="section"]');
            sectionField?.removeAttribute('disabled');
            const fileInput = resourceForm.querySelector('[name="file"]');
            const urlInput = resourceForm.querySelector('[name="external_url"]');
            fileInput?.removeAttribute('disabled');
            urlInput?.removeAttribute('disabled');
            const response = await fetch(urls.resourceUpsert, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken },
                body: formData,
            });
            if (response.ok) {
                toggleModal('resourceModal', false);
                resourceForm.reset();
                toggleResourceInputs(resourceForm);
                refreshPortalData();
            }
        });

        const eventForm = document.getElementById('eventForm');
        eventForm?.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!urls.eventCreate) return;
            const formData = new FormData(eventForm);
            const response = await fetch(urls.eventCreate, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken },
                body: formData,
            });
            if (response.ok) {
                toggleModal('eventModal', false);
                eventForm.reset();
                refreshPortalData();
            }
        });

        const announcementForm = document.getElementById('announcementForm');
        announcementForm?.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!urls.announcementCreate) return;
            const formData = new FormData(announcementForm);
            const response = await fetch(urls.announcementCreate, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrftoken },
                body: formData,
            });
            if (response.ok) {
                toggleModal('announcementModal', false);
                announcementForm.reset();
                refreshPortalData();
            }
        });
    }

    renderSections();
    renderAnnouncements({ announcements: initialAnnouncements });
    initCalendar();
    attachModalTriggers();
    bindDynamicActions();
    bindForms();
    refreshPortalData();
});
