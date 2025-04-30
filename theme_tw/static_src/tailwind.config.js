/**
 * This is a minimal config.
 *
 * If you need the full config, get it from here:
 * https://unpkg.com/browse/tailwindcss@latest/stubs/defaultConfig.stub.js
 */

/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: 'class',
    content: [
        '../../**/*.{html,js}',  // Cover all HTML and JS files
        '../../templates/**/*.html',
        '../../*/templates/**/*.html',
        '../../accesslog/templates/**/*.html',
        '../../contracts/templates/**/*.html',
        '../../inventory/templates/**/*.html',
        '../../processing/templates/**/*.html',
        '../../users/templates/**/*.html',
        '../../theme_tw/templates/**/*.html',
        '../templates/**/*.html',
        '../../static/**/*.js',
    ],
    theme: {
        extend: {},
    },
    plugins: [
        /**
         * '@tailwindcss/forms' is the forms plugin that provides a minimal styling
         * for forms. If you don't like it or have own styling for forms,
         * comment the line below to disable '@tailwindcss/forms'.
         */
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/aspect-ratio'),
    ],
}
