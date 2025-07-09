document.addEventListener('DOMContentLoaded', function() {
    // --- UPDATED: Reading data from the new json_script tag ---
    const dataElement = document.getElementById('unavailable-ranges-data');
    let unavailableRanges = []; // Default to an empty array

    if (dataElement) {
        try {
            const parsedData = JSON.parse(dataElement.textContent);
            // Ensure the parsed data is an array before using it
            if (Array.isArray(parsedData)) {
                unavailableRanges = parsedData;
            } else {
                console.error('Parsed unavailable ranges data is not an array:', parsedData);
            }
        } catch (e) {
            console.error('Failed to parse unavailable ranges JSON:', e);
        }
    } else {
        console.warn('Unavailable ranges data element not found.');
    }

    const dataContainer = document.getElementById('calendar-data-container');
    if (!dataContainer) {
        console.error('Calendar data container not found!');
        return;
    }

    // Get all the necessary elements and data from the data attributes
    const startDateInput = document.getElementById('id_start_date');
    const endDateInput = document.getElementById('id_end_date');
    const submitButton = document.querySelector('button[type="submit"]');
    const errorMessageDiv = document.getElementById('date-validation-error');

    const availableAfterString = dataContainer.dataset.availableAfter;
    const errorMsgEndDate = dataContainer.dataset.errorMsgEndDate;

    if (!startDateInput || !endDateInput || !submitButton || !errorMessageDiv) {
        console.error('One or more required form elements are missing from the DOM.');
        return;
    }

    const disabledDates = unavailableRanges.map(range => ({
        from: range.start,
        to: range.end
    }));

    // --- 1. Determine the minimum selectable date ---
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    let minDate = tomorrow;
    if (availableAfterString) {
        const availableDate = new Date(availableAfterString + 'T00:00:00');
        if (availableDate > tomorrow) {
            minDate = availableDate;
        }
    }

    function validateDates() {
        errorMessageDiv.style.display = 'none';
        errorMessageDiv.textContent = '';
        submitButton.disabled = false;

        const start = startDateInput.value;
        const end = endDateInput.value;

        if (!start || !end) {
            submitButton.disabled = true;
            return;
        }

        const startDate = new Date(start + 'T00:00:00');
        const endDate = new Date(end + 'T00:00:00');

        if (startDate > endDate) {
            errorMessageDiv.textContent = errorMsgEndDate;
            errorMessageDiv.style.display = 'block';
            submitButton.disabled = true;
        }
    }

    // --- 2. Initialize Flatpickr calendars ---
    const fpStart = flatpickr(startDateInput, {
        dateFormat: "d-m-Y",
        minDate: minDate,
        disable: disabledDates,
        onChange: function(selectedDates, dateStr, instance) {
            if (selectedDates[0]) {
                const selectedStartDate = selectedDates[0];

                fpEnd.set('minDate', selectedStartDate);
                endDateInput.disabled = false;

                let nextUnavailableStart = null;
                for (const range of unavailableRanges) {
                    const rangeStart = new Date(range.start);
                    if (rangeStart > selectedStartDate) {
                        if (!nextUnavailableStart || rangeStart < nextUnavailableStart) {
                            nextUnavailableStart = rangeStart;
                        }
                    }
                }

                if (nextUnavailableStart) {
                    const maxDate = new Date(nextUnavailableStart.getTime());
                    maxDate.setDate(maxDate.getDate() - 4); // Buffer
                    fpEnd.set('maxDate', maxDate);
                } else {
                    fpEnd.set('maxDate', null);
                }

                if (endDateInput.value && (new Date(endDateInput.value) < selectedStartDate || (nextUnavailableStart && new Date(endDateInput.value) > nextUnavailableStart))) {
                    fpEnd.clear();
                }
            }
            validateDates();
        }
    });

    const fpEnd = flatpickr(endDateInput, {
        dateFormat: "d-m-Y",
        minDate: minDate,
        disable: disabledDates,
        onChange: function(selectedDates, dateStr, instance) {
            validateDates();
        }
    });

    endDateInput.disabled = true;
    validateDates();
});
