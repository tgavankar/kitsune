(function() {
    $(document).ready(function() {
        var s = new io.Socket(window.location.hostname, {
          port: 3000,
          rememberTransport: false,
          transports: ['websocket', 'xhr-multipart', 'xhr-polling'],
          resource: 'socket.io'
        });
        s.connect();

        s.addEvent('connect', function() {
            s.send('Joined:' + $("#chatform input[name=nonce]").val());
        });
        
        s.addEvent('reconnect', function() {
            s.send('Joined:' + $("#chatform input[name=nonce]").val());
        });

        s.addEvent('message', function(data) {
            var $chatbox = $("#chatbox");
            $chatbox.append("<div>" + data + "</div>").scrollTop($chatbox[0].scrollHeight);
        });
        
        //send the message when submit is clicked
        $('#chatform').submit(function (evt) {
            var line = $('#chatform [type=text]').val();
            if (line !== '') {
                $('#chatform [type=text]').val('');
                s.send(line);
            }
            $(this).trigger('ajaxComplete');
            return false;
        });
    });
})();
