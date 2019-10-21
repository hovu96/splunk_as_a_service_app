const appName = window.location.pathname.match(/..-..\/app\/(?<app>[^\/]+)/).groups.app;

require([
    "jquery",
    "splunkjs/splunk",
    "/static/app/" + appName + "/modal.js",
    "/static/app/" + appName + "/utils.js",
    "splunkjs/ready!"
], function (
    $,
    splunkjs,
    Modal,
    Utils,
    _
) {
    var endpoint = Utils.createRestEndpoint();

    $("#setupButton").click(function () {
        const progressIndicator = Utils.newLoadingIndicator({
            title: "Saving Settings ...",
            subtitle: "Please wait."
        });

        var options = {};
        $('.setup_option').each(function () {
            var el = $(this);
            var value = el.attr('value');
            if (!value) value = "";
            options[el.attr("name")] = value;
        });

        endpoint.post('configure', options, function (err, response) {
            if (err) {
                progressIndicator.hide();
                console.log(err.response.headers["x-saas-is-configured"]);
                const isConfigured = Utils.normalizeBoolean(err.response.headers["x-saas-is-configured"]);
                const dialog = Utils.showErrorDialog(null, err);
                dialog.footer.append($('<button>Continue Setup</button>').attr({
                    type: 'button',
                    'data-dismiss': 'modal',
                    class: "btn btn-primary",
                }));
                if (isConfigured) {
                    dialog.footer.append($('<button class="btn">Back to Home</button>').attr({
                        type: 'button',
                    }).on('click', function () {
                        window.location.href = "/app/" + appName;
                    }));
                }
            } else {
                window.location.href = "/app/" + appName;
            }
        });
    });

    const loadingIndicator = Utils.newLoadingIndicator({
        title: "Loading Settings ...",
        subtitle: "Please wait."
    });
    endpoint.get('configure', {}, function (err, response) {
        loadingIndicator.hide();
        if (err) {
            Utils.showErrorDialog(null, err).footer.append($('<button>Retry</button>').attr({
                type: 'button',
                class: "btn btn-primary",
            }).on('click', function () {
                window.location.reload();
            }));
            return;
        }

        $('.setup_option').each(function () {
            const el = $(this);
            const name = el.attr("name");
            var value = response.data[name];
            /*if (name == "......") {
                if (!value) {
                    value = "....";
                }
            }*/
            el.attr('value', value);
        });
    });

});
