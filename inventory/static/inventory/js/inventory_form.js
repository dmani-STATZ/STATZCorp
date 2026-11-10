(function () {
    'use strict';

    var money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

    function initAutocomplete() {
        if (!window.jQuery || !jQuery.fn.autocomplete) return;
        var form = document.getElementById('invItemForm');
        if (!form) return;
        jQuery(form).find('[data-autocomplete-url]').each(function () {
            var input = jQuery(this);
            input.autocomplete({
                source: input.attr('data-autocomplete-url'),
                minLength: 1,
                appendTo: form
            });
        });
    }

    function initTotal() {
        var qty = document.getElementById('id_quantity');
        var price = document.getElementById('id_purchaseprice');
        var out = document.getElementById('invFormTotal');
        if (!qty || !price || !out) return;

        function update() {
            var q = qty.value.trim();
            var p = price.value.trim();
            var qn = Number(q);
            var pn = Number(p);
            if (q === '' || p === '' || !isFinite(qn) || !isFinite(pn)) {
                out.textContent = '\u2014';
                return;
            }
            out.textContent = money.format(qn * pn);
        }

        qty.addEventListener('input', update);
        price.addEventListener('input', update);
        update();
    }

    document.addEventListener('DOMContentLoaded', function () {
        initAutocomplete();
        initTotal();
    });
})();
