document.addEventListener('DOMContentLoaded', () => {
    initAddressPickers();
    initToggleControls();
});

function initAddressPickers() {
    const pickers = document.querySelectorAll('.address-picker');
    if (!pickers.length) {
        return;
    }

    pickers.forEach((picker) => {
        const selectId = picker.dataset.selectId;
        const selectElement = document.getElementById(selectId);
        if (!selectElement) {
            return;
        }

        const buttons = Array.from(picker.querySelectorAll('.address-option'));

        const setActive = (value) => {
            buttons.forEach((btn) => {
                const isActive = btn.dataset.value === value;
                btn.classList.toggle('border-blue-500', isActive);
                btn.classList.toggle('bg-blue-50', isActive);
                btn.classList.toggle('text-blue-700', isActive);
                btn.classList.toggle('border-gray-200', !isActive);
                btn.classList.toggle('text-gray-600', !isActive);
            });
        };

        buttons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const { value } = btn.dataset;
                selectElement.value = value;
                setActive(value);
            });
        });

        // Initialize state with current select value
        setActive(selectElement.value);
    });
}

function initToggleControls() {
    const toggles = document.querySelectorAll('.toggle-control');
    if (!toggles.length) {
        return;
    }

    toggles.forEach((control) => {
        const checkboxId = control.dataset.checkboxId;
        const checkbox = document.getElementById(checkboxId);
        if (!checkbox) {
            return;
        }

        const onButton = control.querySelector('[data-value="true"]');
        const offButton = control.querySelector('[data-value="false"]');

        const setState = (state) => {
            checkbox.checked = state;

            if (onButton) {
                onButton.classList.toggle('bg-green-500', state);
                onButton.classList.toggle('text-white', state);
                onButton.classList.toggle('bg-white', !state);
                onButton.classList.toggle('text-gray-500', !state);
            }

            if (offButton) {
                offButton.classList.toggle('bg-red-500', !state);
                offButton.classList.toggle('text-white', !state);
                offButton.classList.toggle('bg-white', state);
                offButton.classList.toggle('text-gray-500', state);
            }
        };

        onButton?.addEventListener('click', () => setState(true));
        offButton?.addEventListener('click', () => setState(false));

        // Initialize based on current checkbox state (default False if unchecked)
        setState(checkbox.checked);
    });
}
